"""Use cases of identity, account security and profiles (workspaces).

A profile owns everything a candidate records: skills, experience, education,
preferences, the jobs analysed under it and the resumes written from it.
Switching profiles switches the whole app; deleting one takes its content with
it. Views call the functions below and only translate the outcome into HTTP
(a redirect, a flash message, a form error); a rule that says "not now" is
raised as `core.exceptions.Blocked` / `Refused` with a message fit to show.

Use cases: docs/use-cases/UC01_IDENTITY_AUTH_SECURITY.md and
UC02_PROFILE_WORKSPACES.md.
"""

from django.conf import settings
from django.contrib.auth import login, logout, update_session_auth_hash
from django.db import IntegrityError, transaction
from django.utils import translation
from django.utils.translation import gettext

from core.exceptions import Blocked, Refused

from .models import Profile, default_profile_language

#: Session key holding the id of the profile the user is currently working in.
ACTIVE_PROFILE_SESSION_KEY = "active_profile_id"


# ---------------------------------------------------------------------------
# UC-01 — Identity, authentication and account security
# ---------------------------------------------------------------------------
# UC-01.1 — User Registration & Auto-Subscription (precondition 2, and the
# "signups disabled" alternative flow: an operator can close registration from
# the staff portal without a deploy).
def signups_open() -> bool:
    from staffportal.domain import runtime_settings

    return bool(runtime_settings.get("signups_enabled"))


# UC-01.1 — User Registration & Auto-Subscription (steps 5-6)
def complete_registration(request, user, profile_language: str) -> None:
    """Finish signing `user` up: give their first profile the language they picked
    on the form, then sign them in.

    By now the account exists, and so do its first profile (the `post_save`
    receiver in accounts/signals.py) and its subscription (staffportal's
    receiver) — the form only asked which language that profile should speak,
    so it is stamped before anything is written under it.
    """
    Profile.objects.filter(user=user).update(language=profile_language)
    login(request, user)


# UC-01.2 — Email Authentication & Session Inception (step 4)
def apply_remember_me(request, remember_me: bool) -> None:
    """Without "remember me" the session ends when the browser does."""
    if not remember_me:
        request.session.set_expiry(0)


# UC-01.4 — Credential Modification (Password Change) (steps 3-4)
def change_password(request, form):
    """Save the new password of a validated `PasswordChangeForm`.

    `update_session_auth_hash` keeps the user signed in: Django would otherwise
    invalidate their session, since it is bound to the password hash.
    """
    user = form.save()
    update_session_auth_hash(request, user)
    return user


# UC-01.6 — Self-Service Account Erasure (GDPR Art. 17) (step 5)
def delete_account(request, user) -> None:
    """Sign `user` out and delete the account with everything it owns.

    Profiles, and through them every skill, experience, job post, resume import
    and tailored resume, go with it by cascade; so do the subscription and the
    usage records. Staff audit entries keep their denormalised email.
    """
    logout(request)
    user.delete()


# ---------------------------------------------------------------------------
# UC-02 — Workspaces (profiles)
# ---------------------------------------------------------------------------
# UC-02.1 / UC-02.2 / UC-02.4 — every workspace lookup is scoped to its owner,
# which is what makes another user's profile a 404 rather than a leak.
def profiles_of(user):
    return Profile.objects.filter(user=user)


def default_profile_name(user) -> str:
    """A unique starter name, so the bootstrap never trips the unique constraint."""
    base = gettext("My profile")
    taken = set(Profile.objects.filter(user=user).values_list("name", flat=True))
    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base} {suffix}"
        if candidate not in taken:
            return candidate
    return f"{base} {user.pk}"


# UC-01.1 — User Registration & Auto-Subscription (step 5a) and UC-02.1
def bootstrap_profile(user, *, language: str | None = None, name: str | None = None) -> Profile:
    """Create this user's first profile.

    Used at registration and as the safety net for accounts that predate
    profiles (or were made by `createsuperuser`, which has no request and so no
    language to read). A profile created here still has a real language — the
    one the user is reading the site in — never a blank one.
    """
    try:
        with transaction.atomic():
            return Profile.objects.create(
                user=user,
                name=name or default_profile_name(user),
                language=language or default_profile_language(),
            )
    except IntegrityError:
        # Two concurrent requests raced to bootstrap the same user.
        return Profile.objects.filter(user=user).first()


# UC-01.2 — Email Authentication & Session Inception (step 5) and UC-02.2
# (step 8: every later request resolves `request.profile` through here).
def get_active_profile(request):
    """The profile the request is working in, or None when the user has none.

    Falls back to the user's oldest profile when the session points at a
    profile that has since been deleted (or at someone else's).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None

    profiles = Profile.objects.filter(user=user)
    profile_id = request.session.get(ACTIVE_PROFILE_SESSION_KEY)
    if profile_id:
        profile = profiles.filter(pk=profile_id).first()
        if profile is not None:
            return profile

    profile = profiles.first()
    if profile is None:
        profile = bootstrap_profile(user)
    if profile is not None:
        set_active_profile(request, profile)
    return profile


# UC-02.1 (step 8) and UC-02.2 (step 4): the session remembers which workspace
# the user is in.
def set_active_profile(request, profile: Profile) -> None:
    request.session[ACTIVE_PROFILE_SESSION_KEY] = profile.pk


# UC-02.1 — Workspace / Profile Creation with Immutable Language Contract (steps 6-8)
def create_profile(request, form) -> Profile:
    """Save the profile a validated `ProfileCreateForm` describes, and make it the
    one the user is working in.

    Workspaces are a ceiling rather than a meter: the check is how many exist,
    not how many were created this month, and it only applies once an operator
    has switched quota enforcement on. Raises `Blocked` when the plan's limit is
    reached.
    """
    from staffportal.domain import quotas

    blocked = quotas.profile_blocked_message(request.user)
    if blocked:
        raise Blocked(blocked)

    profile = form.save()
    set_active_profile(request, profile)
    return profile


# UC-02.2 — Active Workspace Switching & Locale Activation (steps 4-5)
def switch_profile(request, profile: Profile) -> None:
    set_active_profile(request, profile)


# UC-02.2 — Active Workspace Switching & Locale Activation (step 6)
def follow_profile_language(response, profile: Profile) -> None:
    """The interface follows the workspace: reading a French profile in an English
    UI would show its content and its labels in two languages."""
    translation.activate(profile.language)
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        profile.language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )


# UC-02.3 — Profile Metadata & Contact Information Updates (step 5)
def update_personal_info(form) -> Profile:
    """Save a validated `ProfileForm`: the name goes to the account, everything
    else to the active profile."""
    return form.save()


# UC-02.4 — Workspace Renaming & Deletion Guards (renaming, step 3)
def rename_profile(form) -> Profile:
    """Save a validated `ProfileRenameForm`. The language is not in it: the content
    recorded under a profile is written in that language, so re-pointing the
    profile would leave it permanently mixed."""
    return form.save()


# UC-02.4 — Workspace Renaming & Deletion Guards (deletion, step 2)
def ensure_profile_deletable(user, profile: Profile) -> None:
    """Refuse to delete the user's last profile.

    With no profile there is nowhere to put anything, and the account-level
    "delete my account" button is the real way out.
    """
    if not Profile.objects.filter(user=user).exclude(pk=profile.pk).exists():
        raise Refused(gettext("You can't delete your only profile — create another one first."))


# UC-02.4 — Workspace Renaming & Deletion Guards (deletion, steps 5-6)
def delete_profile(request, profile: Profile) -> None:
    """Delete `profile` and everything recorded in it. When it was the one the user
    was working in, another of their profiles becomes the active one.

    Raises `Refused` for the user's only profile.
    """
    ensure_profile_deletable(request.user, profile)
    remaining = Profile.objects.filter(user=request.user).exclude(pk=profile.pk)
    was_active = request.profile and request.profile.pk == profile.pk
    profile.delete()
    if was_active:
        set_active_profile(request, remaining.first())
