"""Helpers for resolving and bootstrapping a user's profiles (workspaces)."""

from django.db import IntegrityError, transaction
from django.utils.translation import gettext

from .models import Profile, default_profile_language

#: Session key holding the id of the profile the user is currently working in.
ACTIVE_PROFILE_SESSION_KEY = "active_profile_id"


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


def set_active_profile(request, profile: Profile) -> None:
    request.session[ACTIVE_PROFILE_SESSION_KEY] = profile.pk
