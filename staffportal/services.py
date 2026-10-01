"""Use cases of the staff portal — the operator console mounted at /staff/.

Three rules run through everything here. Every screen goes through one gate
(`portal_gate`, UC-08.1); every mutation writes an audit entry (UC-08.10); and
the actions that can hurt someone — impersonation, deletion, data export — each
need a capability of their own rather than riding along with "staff"
(UC-08.3, UC-08.11).

`staffportal/views/` reads the request, calls one function below and turns the
outcome into a redirect and a flash message: a `Refused` (a rule says no) or a
`PreconditionFailed` (the thing it works on is not in the state it needs) is an
error message whose text is fit to show. `request` is passed to whatever writes
an audit entry, because the entry records who acted, from where and whether they
were impersonating at the time.

The building blocks these compose — capabilities, audit, exports, flags, health,
impersonation, metrics, quotas, runtime settings, subscriptions — are in
`staffportal/domain/`.

Use cases: docs/use-cases/UC08_STAFF_OPERATIONS_ADMIN.md (and UC-01.1 for the
subscription every new account gets).
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.forms import PasswordResetForm
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from core.exceptions import PreconditionFailed, Refused, ServiceError
from core.models import AITask
from jobs.models import JobPost
from resume.models import ResumeImport, TailoredResume

from .domain import (
    access,
    audit,
    exports,
    flags,
    health,
    impersonation,
    metrics,
    quotas,
    runtime_settings,
    subscriptions,
)
from .models import (
    Announcement,
    AuditLog,
    FeatureFlag,
    ImpersonationSession,
    Plan,
    StaffMember,
    Subscription,
    SupportNote,
    UsageRecord,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# UC-08.1 — Granular Role-Based Access Control & Portal Obfuscation
# ---------------------------------------------------------------------------
#: What `portal_gate` can decide.
ALLOW = "allow"
LOGIN = "login"
HIDDEN = "hidden"
FORBIDDEN = "forbidden"


# UC-08.1 — steps 2-4
def portal_gate(request, capability: str) -> str:
    """What a visitor gets for a screen that needs `capability`.

    * `LOGIN` — not signed in.
    * `HIDDEN` — answer 404, not 403: a 403 confirms the portal exists at this
      URL. That is what a non-staff visitor gets, and also what a session that
      is impersonating a customer gets, whoever started it — otherwise "sign in
      as a customer" would be a way to act as staff through a session the audit
      trail attributes to the customer.
    * `FORBIDDEN` — staff who are merely missing the capability. They already
      know the portal is here, and a silent 404 would look like a broken link.
    * `ALLOW`.
    """
    user = request.user
    if not user.is_authenticated:
        return LOGIN
    if impersonation.is_impersonating(request):
        return HIDDEN
    if not (user.is_staff and user.is_active):
        return HIDDEN
    if not access.has_capability(user, capability):
        return FORBIDDEN
    return ALLOW


# UC-08.1 — step 2: what the "you can't open this" page says
def forbidden_context(user, capability: str, section: str) -> dict:
    return {
        "capability": capability,
        "capability_label": access.CAPABILITY_LABELS.get(capability, capability),
        "role_label": access.role_label(user),
        "section": section,
    }


# UC-08.1 — step 3: the role and capabilities every portal screen shows in its chrome
def portal_context(user) -> dict:
    return {
        "portal_role": access.role_label(user),
        "portal_capabilities": access.capabilities_for(user),
    }


# UC-08.1 — Team access (superuser-only, by design: a role that can hand out
# roles can promote itself, which would make every other boundary decorative)
def team_members():
    return StaffMember.objects.select_related("user", "created_by")


# UC-08.1 — staff accounts with no role row are real: they read as viewers
def unmanaged_staff():
    return User.objects.filter(is_staff=True, staff_member__isnull=True)


# UC-08.1 — the capabilities matrix
def role_matrix() -> list:
    return [(role.label, sorted(access.ROLE_CAPABILITIES[role])) for role in access.StaffRole]


# UC-08.1 — granting portal access, by email
def grant_portal_access(request, form) -> tuple:
    """Give the account a validated `StaffAccessForm` names its role. Returns
    `(member, created)`; the account becomes staff if it was not already."""
    account = form.user
    member, created = StaffMember.objects.update_or_create(
        user=account,
        defaults={
            "role": form.cleaned_data["role"],
            "note": form.cleaned_data["note"],
            "created_by": request.user,
        },
    )
    if not account.is_staff:
        account.is_staff = True
        account.save(update_fields=["is_staff"])
    audit.log(
        request,
        audit.TEAM_GRANTED if created else audit.TEAM_UPDATED,
        target=account,
        summary=f"Portal access as {member.get_role_display()}.",
        role=member.role,
    )
    return member, created


# UC-08.1 — changing a role
def change_staff_role(request, form) -> StaffMember:
    member = form.save()
    audit.log(
        request, audit.TEAM_UPDATED, target=member.user,
        summary=f"Role set to {member.get_role_display()}.", role=member.role,
    )
    return member


# UC-08.1 — revoking access. Raises `Refused` for your own.
def revoke_portal_access(request, member: StaffMember) -> None:
    account = member.user
    if account.pk == request.user.pk:
        raise Refused("You cannot revoke your own access.")

    member.delete()
    # Revoking the role without clearing `is_staff` would leave a viewer
    # behind, which is not what "revoke" means to the person clicking it.
    if account.is_staff and not account.is_superuser:
        account.is_staff = False
        account.save(update_fields=["is_staff"])
    audit.log(request, audit.TEAM_REVOKED, target=account, summary="Portal access revoked.")


# UC-08.1 — the overview an operator lands on: growth, revenue, engagement and
# the state of the machine
def dashboard(user, days: int) -> dict:
    ctx = {"days": days}
    ctx.update(metrics.overview(days))

    checks = health.run_checks()
    ctx["health_summary"] = health.summarize(checks)
    # Only the problems here — the full list has its own screen.
    ctx["health_problems"] = [c for c in checks if c.status != health.OK][:4]

    ctx["recent_signups"] = (
        User.objects.select_related("subscription__plan").order_by("-date_joined")[:8]
    )
    ctx["recent_failures"] = (
        AITask.objects.filter(state=AITask.FAILED)
        .select_related("user")
        .order_by("-finished_at")[:5]
    )
    if access.has_capability(user, access.IMPERSONATE):
        ctx["open_impersonations"] = ImpersonationSession.objects.filter(
            ended_at__isnull=True
        ).order_by("-started_at")[:5]
    return ctx


# ---------------------------------------------------------------------------
# UC-08.2 — Customer Account Administration, Filtering & Session-Flushing Suspension
# ---------------------------------------------------------------------------
def accounts():
    return User.objects.all()


# UC-08.2 — step 3: the account detail page's lookup
def accounts_with_subscription():
    return User.objects.select_related("subscription__plan", "staff_member")


# UC-08.2 — step 1: how many accounts there are, above the list
def account_count() -> int:
    return User.objects.count()


# UC-08.2 (the plan filter) and UC-08.5 (the plans to choose from)
def list_plans():
    return Plan.objects.all()


def _accounts_queryset():
    """One query shape for the list and its CSV export, so the file and the
    screen can never disagree about what a row means."""
    return (
        User.objects.select_related("subscription__plan")
        .annotate(
            profile_count=Count("profiles", distinct=True),
            job_post_count=Count("profiles__job_posts", distinct=True),
        )
        .order_by("-date_joined")
    )


def _apply_account_filters(queryset, params):
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    status = params.get("status", "")
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "suspended":
        queryset = queryset.filter(is_active=False)
    elif status == "staff":
        queryset = queryset.filter(is_staff=True)

    plan = params.get("plan", "")
    if plan.isdigit():
        queryset = queryset.filter(subscription__plan_id=int(plan))

    activity = params.get("activity", "")
    cutoff = timezone.now() - timedelta(days=30)
    if activity == "recent":
        queryset = queryset.filter(last_seen_at__gte=cutoff)
    elif activity == "dormant":
        queryset = queryset.filter(Q(last_seen_at__lt=cutoff) | Q(last_seen_at__isnull=True))
    return queryset


# UC-08.2 — step 2: search and filter (status, plan, activity)
def search_accounts(params):
    return _apply_account_filters(_accounts_queryset(), params)


# UC-08.2 — the filtered list as a CSV. Downloads are audited (UC-08.10).
def export_accounts(request, params):
    queryset = search_accounts(params)
    audit.log(
        request,
        audit.EXPORT_DOWNLOADED,
        summary=f"Accounts CSV ({queryset.count()} rows).",
        filters=dict(params.items()),
    )
    return exports.stream_csv(
        exports.timestamped("accounts"), exports.USER_HEADER, exports.user_rows(queryset)
    )


# UC-08.2 — step 3: everything support needs on one account
def account_overview(account, operator) -> dict:
    profiles = account.profiles.all()
    subscription = subscriptions.ensure_subscription(account)
    profile_limit, profile_used = quotas.profile_limit(account)
    can_impersonate, impersonate_blocked_reason = access.can_impersonate(operator, account)
    return {
        "account": account,
        "profiles": profiles,
        "subscription": subscription,
        "allowances": quotas.summary(account),
        "profile_limit": profile_limit,
        "profile_used": profile_used,
        "quotas_enforced": quotas.enforcement_enabled(),
        "job_posts": JobPost.objects.filter(profile__in=profiles).order_by("-created_at")[:10],
        "job_post_count": JobPost.objects.filter(profile__in=profiles).count(),
        "tailored_count": TailoredResume.objects.filter(profile__in=profiles).count(),
        "tasks": AITask.objects.filter(user=account).order_by("-queued_at")[:10],
        "notes": SupportNote.objects.filter(user=account).select_related("author"),
        "enabled_flags": sorted(flags.enabled_for(account)),
        "impersonations": ImpersonationSession.objects.filter(target=account)[:5],
        "audit_entries": AuditLog.objects.filter(
            target_type="accounts.user", target_id=str(account.pk)
        )[:10],
        "can_impersonate": can_impersonate,
        "impersonate_blocked_reason": impersonate_blocked_reason,
    }


# UC-08.2 — step 4: suspension. Raises `Refused` for your own account, and for a
# superuser's unless you are one.
def suspend_account(request, account, reason: str) -> None:
    if account.pk == request.user.pk:
        raise Refused("You cannot suspend your own account.")
    if account.is_superuser and not request.user.is_superuser:
        raise Refused("Only a superuser may suspend a superuser.")

    account.is_active = False
    account.save(update_fields=["is_active"])
    # Suspension has to end the sessions the account already holds, otherwise it
    # only stops them signing in *again*.
    _flush_sessions(account)
    audit.log(
        request,
        audit.USER_SUSPENDED,
        target=account,
        summary=reason or "Account suspended.",
    )


# UC-08.2 — step 4 (the way back)
def reactivate_account(request, account) -> None:
    account.is_active = True
    account.save(update_fields=["is_active"])
    audit.log(request, audit.USER_REACTIVATED, target=account, summary="Account reactivated.")


def _flush_sessions(account) -> None:
    """End every signed-in session belonging to `account`.

    Django keeps sessions as opaque blobs, so there is no index from user to
    session — the honest way is to decode the unexpired ones and drop the
    matches. Fine at this scale; swap for a session backend with a user column
    if the table ever gets large.
    """
    from django.contrib.sessions.models import Session

    target = str(account.pk)
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            if session.get_decoded().get("_auth_user_id") == target:
                session.delete()
        except Exception:  # pragma: no cover — a corrupt session is not our problem
            continue


# UC-08.2 — sending the customer the normal reset email
def send_password_reset(request, account) -> None:
    """Staff never see or set a customer's password: the reset goes to the address
    on the account, so the customer is the only one who ends up knowing it.
    Raises `PreconditionFailed` for an address that cannot receive it."""
    form = PasswordResetForm({"email": account.email})
    if not form.is_valid():
        raise PreconditionFailed("That address cannot receive a reset email.")
    form.save(
        request=request,
        use_https=request.is_secure(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        email_template_name="accounts/emails/password_reset_email.txt",
        html_email_template_name="accounts/emails/password_reset_email.html",
        subject_template_name="accounts/emails/password_reset_subject.txt",
        extra_email_context={"site_name": settings.SITE_NAME},
    )
    audit.log(
        request,
        audit.USER_PASSWORD_RESET_SENT,
        target=account,
        summary="Password reset email sent.",
    )


# ---------------------------------------------------------------------------
# UC-08.3 — Audited, Time-Limited Customer Impersonation
# ---------------------------------------------------------------------------
# UC-08.3 — steps 1-5
def start_impersonation(request, account, form) -> ImpersonationSession:
    """Sign the operator in as `account`, for a stated reason.

    `form` is the bound `ImpersonationForm`; it is checked after the eligibility
    rules, so the operator hears about the more fundamental problem first.
    Raises `Refused` (yourself, a suspended account, another staff member's
    unless you are a superuser) and `PreconditionFailed` (no reason).
    """
    allowed, reason = access.can_impersonate(request.user, account)
    if not allowed:
        raise Refused(reason)
    if not form.is_valid():
        raise PreconditionFailed("A reason is required before impersonating an account.")
    return impersonation.start(request, account, form.cleaned_data["reason"])


# UC-08.3 — step 8: hand the session back
def stop_impersonation(request):
    """End the impersonation this request is part of.

    Returns the staff member the session was handed back to, or None when the
    impersonation record had already gone — the customer's session is then
    signed out rather than left open. Raises `PreconditionFailed` when the
    request is not impersonating anyone.
    """
    if not impersonation.is_impersonating(request):
        raise PreconditionFailed("You are not signed in as another account.")
    staff_user = impersonation.stop(request)
    if staff_user is None:
        logout(request)
    return staff_user


# UC-08.3 — the log of every time a staff account signed in as a customer
def impersonation_sessions():
    impersonation.close_expired()
    return ImpersonationSession.objects.select_related("actor", "target")


# UC-08.3 — the session "automatically expires" (safety invariant 2)
def apply_impersonation_lifetime(request) -> None:
    """Called on every request. Expiry is checked on the impersonated user's own
    requests, so a forgotten session ends the next time anyone touches it rather
    than lingering until someone remembers."""
    request.impersonator = None
    if impersonation.is_impersonating(request):
        record = impersonation.current_session(request)
        if record is None or not record.is_open:
            staff_user = impersonation.stop(request, ImpersonationSession.EXPIRED)
            if staff_user is None:
                logout(request)
        else:
            request.impersonator = impersonation.actor(request)
            request.impersonation_session = record


# ---------------------------------------------------------------------------
# UC-08.4 — Internal Customer Support Annotations
# ---------------------------------------------------------------------------
# UC-08.4 — steps 3-5
def add_support_note(request, account, form) -> SupportNote:
    """Save the note a validated `SupportNoteForm` holds against `account`,
    stamped with who wrote it. Notes are internal and never shown to customers."""
    note = form.save(commit=False)
    note.user = account
    note.author = request.user
    note.author_email = request.user.email
    note.save()
    audit.log(request, audit.USER_NOTE_ADDED, target=account, summary="Support note added.")
    return note


# ---------------------------------------------------------------------------
# UC-08.5 — Plan Tier Definition & Subscription Management
# ---------------------------------------------------------------------------
# UC-08.5 — step 1
def billing_overview() -> dict:
    return {
        "revenue": metrics.revenue(),
        "breakdown": metrics.plan_breakdown(),
        "plans": Plan.objects.annotate(
            subscriber_count=Count(
                "subscriptions",
                filter=Q(subscriptions__status__in=Subscription.ENTITLED_STATUSES),
            )
        ),
    }


# UC-08.5 — step 2: how many customers a plan currently entitles
def entitled_subscriber_count(plan: Plan) -> int:
    return plan.subscriptions.filter(status__in=Subscription.ENTITLED_STATUSES).count()


# UC-08.5 — step 2 (creating a plan)
def create_plan(request, form) -> Plan:
    plan = form.save()
    audit.log(
        request, audit.PLAN_CREATED, target=plan,
        summary=f"Plan created at {plan.price_display}.",
    )
    return plan


# UC-08.5 — step 2 (editing a plan)
def update_plan(request, form) -> Plan:
    changed = ", ".join(form.changed_data) or "nothing"
    plan = form.save()
    audit.log(
        request, audit.PLAN_UPDATED, target=plan,
        summary=f"Changed: {changed}.", fields=form.changed_data,
    )
    return plan


#: What `retire_plan` did.
PLAN_MISSING = "missing"
PLAN_DEACTIVATED = "deactivated"
PLAN_DELETED = "deleted"


# UC-08.5 — retiring a plan
def retire_plan(request, pk) -> tuple:
    """Delete plan `pk` — or, when it has subscribers, deactivate it instead.

    A plan with subscribers is never deleted: `Subscription.plan` is PROTECTed
    and, more to the point, deleting it would erase what those customers agreed
    to pay. Returns `(outcome, plan name)`.
    """
    plan = Plan.objects.filter(pk=pk).first()
    if plan is None:
        return PLAN_MISSING, ""
    if plan.subscriptions.exists():
        plan.is_active = False
        plan.is_default = False
        plan.save(update_fields=["is_active", "is_default", "updated_at"])
        audit.log(
            request, audit.PLAN_UPDATED, target=plan,
            summary="Plan deactivated (it still has subscribers, so it was not deleted).",
        )
        return PLAN_DEACTIVATED, plan.name

    name = plan.name
    audit.log(request, audit.PLAN_UPDATED, target=plan, summary="Plan deleted.")
    plan.delete()
    return PLAN_DELETED, name


# UC-08.5 — the list of subscriptions, by state
def search_subscriptions(params):
    queryset = Subscription.objects.select_related("user", "plan")
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(user__email__icontains=query)
            | Q(external_customer_id__icontains=query)
            | Q(external_subscription_id__icontains=query)
        )
    status = params.get("status", "")
    if status in dict(Subscription.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    plan = params.get("plan", "")
    if plan.isdigit():
        queryset = queryset.filter(plan_id=int(plan))
    return queryset


# UC-08.5 — a subscription edited by hand
def update_subscription(request, form) -> Subscription:
    changed = ", ".join(form.changed_data) or "nothing"
    if "status" in form.changed_data and form.cleaned_data["status"] in (
        Subscription.CANCELED,
        Subscription.EXPIRED,
    ):
        # Churn is measured from this timestamp, so it is set here rather than
        # left to whoever remembers.
        form.instance.canceled_at = form.instance.canceled_at or timezone.now()
    subscription = form.save()
    audit.log(
        request, audit.SUBSCRIPTION_UPDATED, target=subscription.user,
        summary=f"Subscription changed: {changed}.", fields=form.changed_data,
    )
    return subscription


# UC-08.5 — step 3: a customer's plan tier or status, changed from their page.
# Raises `PreconditionFailed` when no plans exist.
def change_account_plan(request, account, plan: Plan, status: str, note: str = "") -> None:
    subscription = subscriptions.ensure_subscription(account)
    if subscription is None:
        raise PreconditionFailed("No plans are configured yet.")

    before = f"{subscription.plan.name}/{subscription.status}"
    subscriptions.change_plan(subscription, plan, status=status)
    audit.log(
        request,
        audit.SUBSCRIPTION_UPDATED,
        target=account,
        summary=f"{before} → {plan.name}/{status}. {note}".strip(),
        plan=plan.slug,
        status=status,
    )


# UC-08.5 — step 4: zero this period's counters — the goodwill gesture after an
# outage ate someone's allowance. Returns how many counters were cleared.
def reset_usage(request, account) -> int:
    subscription = subscriptions.ensure_subscription(account)
    if subscription is None:
        raise PreconditionFailed("No plans are configured yet.")
    start, _end = subscriptions.current_period(subscription)
    cleared = UsageRecord.objects.filter(user=account, period_start=start).update(count=0)
    audit.log(
        request,
        audit.USAGE_RESET,
        target=account,
        summary=f"Reset {cleared} usage counter(s) for the current period.",
    )
    return cleared


# UC-08.5 — the subscriptions list as a CSV
def export_subscriptions(request, params):
    queryset = search_subscriptions(params)
    audit.log(
        request, audit.EXPORT_DOWNLOADED,
        summary=f"Subscriptions CSV ({queryset.count()} rows).",
    )
    return exports.stream_csv(
        exports.timestamped("subscriptions"),
        exports.SUBSCRIPTION_HEADER,
        exports.subscription_rows(queryset),
    )


# UC-01.1 — User Registration & Auto-Subscription (step 6)
def provision_subscription(user) -> None:
    """Give a new account its subscription the moment it exists, so no code path
    anywhere has to cope with a user that has no plan, and the portal's
    subscriber count matches the account count on day one."""
    subscriptions.ensure_subscription(user)


#: The starter plans a new deployment needs. Never rewritten once they exist:
#: the price someone is already paying is not something a deploy script should be
#: allowed to change.
STARTER_PLANS = [
    {
        "slug": "free",
        "name": "Free",
        "tagline": "Try it on a couple of postings.",
        "price_cents": 0,
        "sort_order": 10,
        "is_default": True,
        "max_profiles": 1,
        "monthly_job_analyses": 5,
        "monthly_tailored_resumes": 2,
        "monthly_resume_imports": 1,
        "features": "1 profile\n5 job analyses a month\n2 tailored resumes a month",
    },
    {
        "slug": "pro",
        "name": "Pro",
        "tagline": "For an active search.",
        "price_cents": 1200,
        "sort_order": 20,
        "max_profiles": 5,
        "monthly_job_analyses": 100,
        "monthly_tailored_resumes": 50,
        "monthly_resume_imports": 20,
        "features": "5 profiles\n100 job analyses a month\n50 tailored resumes a month\nPDF export",
    },
    {
        "slug": "unlimited",
        "name": "Unlimited",
        "tagline": "No ceilings.",
        "price_cents": 2900,
        "sort_order": 30,
        "max_profiles": None,
        "monthly_job_analyses": None,
        "monthly_tailored_resumes": None,
        "monthly_resume_imports": None,
        "features": "Unlimited profiles\nUnlimited analyses\nUnlimited resumes\nPriority support",
    },
]

STARTER_FLAGS = [
    {
        "key": "pricing-page",
        "name": "Public pricing page",
        "description": "Shows plans and prices to signed-out visitors.",
        "state": FeatureFlag.OFF,
    },
    {
        "key": "usage-meter",
        "name": "Usage meter in the app",
        "description": "Shows customers how much of this month's allowance they have used.",
        "state": FeatureFlag.STAFF,
    },
]


# UC-08.5 — Plan Tier Definition (the plans a fresh deployment starts with) and
# UC-08.6 (its starter flags)
@transaction.atomic
def seed_starter_data(*, backfill: bool = False) -> dict:
    """Create the starter plans and flags that do not exist yet; idempotent, so it
    is safe to run on every deploy. With `backfill`, accounts that have no
    subscription are put on the default plan.

    Returns `{"plans": [(plan, created)], "flags": [(flag, created)],
    "backfilled": int | None}`.
    """
    seeded_plans = []
    for spec in STARTER_PLANS:
        plan, created = Plan.objects.get_or_create(
            slug=spec["slug"], defaults={k: v for k, v in spec.items() if k != "slug"}
        )
        seeded_plans.append((plan, created))

    seeded_flags = []
    for spec in STARTER_FLAGS:
        flag, created = FeatureFlag.objects.get_or_create(
            key=spec["key"], defaults={k: v for k, v in spec.items() if k != "key"}
        )
        seeded_flags.append((flag, created))

    backfilled = None
    if backfill:
        backfilled = 0
        for user in User.objects.filter(subscription__isnull=True):
            if subscriptions.ensure_subscription(user):
                backfilled += 1
    return {"plans": seeded_plans, "flags": seeded_flags, "backfilled": backfilled}


# ---------------------------------------------------------------------------
# UC-08.6 — Dynamic Deterministic Feature Flags & Account Overrides
# ---------------------------------------------------------------------------
# UC-08.6 — step 1
def list_flags():
    return FeatureFlag.objects.prefetch_related("plans", "users")


# UC-08.6 — step 3: what the signed-in operator would get. A flag list that does
# not say this invites "it's on, why can't I see it?".
def flags_enabled_for(user) -> set:
    return flags.enabled_for(user)


# UC-08.6 — step 2
def save_flag(request, form, *, created: bool) -> FeatureFlag:
    form.instance.updated_by = request.user
    flag = form.save()
    audit.log(
        request,
        audit.FLAG_CREATED if created else audit.FLAG_UPDATED,
        target=flag,
        summary=f"{flag.key} → {flag.state_summary}.",
        state=flag.state,
        percentage=flag.percentage,
    )
    return flag


# UC-08.6 — retiring a flag. Evaluation fails closed, so a key with no row reads
# as off everywhere. Returns the key, or None when there was no such flag.
def delete_flag(request, pk) -> str | None:
    flag = FeatureFlag.objects.filter(pk=pk).first()
    if flag is None:
        return None
    key = flag.key
    audit.log(
        request, audit.FLAG_DELETED, target=flag,
        summary=f"Flag {key} deleted — it now evaluates as off everywhere.",
    )
    flag.delete()
    return key


# ---------------------------------------------------------------------------
# UC-08.7 — Runtime Configuration & Emergency Service Kill Switches
# ---------------------------------------------------------------------------
# UC-08.7 — step 3
def save_settings(request, values: dict) -> list:
    """Write the settings in `values` (a validated `SystemSettingsForm`'s cleaned
    data) that differ from what is stored, and say what changed — the audit entry
    reads "maintenance_mode: False → True", not "settings saved". Returns those
    changes, empty when nothing differed."""
    changed = []
    current = runtime_settings.all_values()
    for spec in runtime_settings.REGISTRY:
        new = values[spec.key]
        if new != current[spec.key]:
            runtime_settings.set_value(spec.key, new, user=request.user)
            changed.append(f"{spec.key}: {current[spec.key]!r} → {new!r}")
    if changed:
        audit.log(
            request, audit.SETTING_UPDATED,
            summary="; ".join(changed)[:300], changes=changed,
        )
    return changed


#: Paths that stay reachable in maintenance mode: the portal itself (so the
#: switch can be turned back off), auth (so staff can sign in to do it), the
#: language switcher, and assets.
MAINTENANCE_EXEMPT_PREFIXES = (
    "/staff/", "/admin/", "/accounts/login", "/accounts/logout", "/i18n/", "/static/", "/media/",
)


# UC-08.7 — the maintenance switch (the kill switches in the settings registry)
def maintenance_blocks(request) -> bool:
    """Whether to serve the maintenance page instead of `request`. Staff keep full
    access on purpose: the point of a maintenance window is to verify the fix
    before letting customers back in."""
    if request.path.startswith(MAINTENANCE_EXEMPT_PREFIXES):
        return False
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return False
    return bool(runtime_settings.get("maintenance_mode"))


#: `User.last_seen_at` is written at most this often per session.
LAST_SEEN_THROTTLE = timedelta(minutes=5)
LAST_SEEN_SESSION_KEY = "last_seen_ping"


# UC-08.2 — step 2: the "activity: recent / dormant" filter (and the engagement
# figures on the overview) read what this writes
def touch_last_seen(request) -> None:
    """Keep `User.last_seen_at` roughly current, through a targeted UPDATE at most
    once every `LAST_SEEN_THROTTLE`: activity metrics are not worth a row write on
    every request, and `last_login` alone counts a user who signed in in March and
    has been using the product daily ever since as a single visit."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return
    now = timezone.now()
    last = request.session.get(LAST_SEEN_SESSION_KEY)
    if last:
        try:
            if now - datetime.fromisoformat(last) < LAST_SEEN_THROTTLE:
                return
        except (TypeError, ValueError):
            pass
    request.session[LAST_SEEN_SESSION_KEY] = now.isoformat()
    User.objects.filter(pk=user.pk).update(last_seen_at=now)


# UC-08.7 — the system health screen
def health_report() -> dict:
    checks = health.run_checks()
    grouped = {}
    for check in checks:
        grouped.setdefault(check.group, []).append(check)
    return {
        "summary": health.summarize(checks),
        "grouped_checks": list(grouped.items()),
        "checked_at": timezone.now(),
    }


# ---------------------------------------------------------------------------
# UC-08.8 — Site-Wide Customer Announcements & In-App Banners
# ---------------------------------------------------------------------------
def list_announcements():
    return Announcement.objects.select_related("created_by")


# UC-08.8 — step 2
def save_announcement(request, form, *, created: bool) -> Announcement:
    if form.instance.pk is None:
        form.instance.created_by = request.user
    announcement = form.save()
    audit.log(
        request,
        audit.ANNOUNCEMENT_CREATED if created else audit.ANNOUNCEMENT_UPDATED,
        target=announcement,
        summary=f"{announcement.title} ({announcement.level}, {announcement.audience}).",
        live=announcement.is_live,
    )
    return announcement


# UC-08.8 — taking one down. Returns its title, or None when there was no such one.
def delete_announcement(request, pk) -> str | None:
    announcement = Announcement.objects.filter(pk=pk).first()
    if announcement is None:
        return None
    title = announcement.title
    audit.log(
        request, audit.ANNOUNCEMENT_DELETED, target=announcement,
        summary=f"Announcement “{title}” deleted.",
    )
    announcement.delete()
    return title


# UC-08.8 — step 3: what a visitor sees at the top of the page — the live ones
# addressed to everyone, to signed-in customers, and (for staff) to staff
def live_announcements_for(user):
    authenticated = bool(user and user.is_authenticated)

    audiences = [Announcement.EVERYONE]
    if authenticated:
        audiences.append(Announcement.AUTHENTICATED)
    if authenticated and user.is_staff:
        audiences.append(Announcement.STAFF)
    return Announcement.objects.live().filter(audience__in=audiences)


# ---------------------------------------------------------------------------
# UC-08.9 — Asynchronous Celery Queue Inspection & Task Re-dispatch
# ---------------------------------------------------------------------------
# UC-08.9 — step 2: the queue, filtered by state, kind and free text
def search_tasks(params):
    queryset = AITask.objects.select_related("user", "profile").order_by("-queued_at")
    state = params.get("state", "")
    if state in dict(AITask.STATE_CHOICES):
        queryset = queryset.filter(state=state)
    kind = params.get("kind", "")
    if kind in dict(AITask.KIND_CHOICES):
        queryset = queryset.filter(kind=kind)
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(user__email__icontains=query) | Q(error_message__icontains=query)
        )
    return queryset


# UC-08.9 — step 2: the counters above the list
def queue_counts() -> dict:
    return {
        "queued": AITask.objects.filter(state=AITask.QUEUED).count(),
        "running": AITask.objects.filter(state=AITask.RUNNING).count(),
        "failed": AITask.objects.filter(state=AITask.FAILED).count(),
    }


# UC-08.9 — step 2: one job in detail — where it is, how long each phase took,
# what it is about and, for job analysis and matching, how far every section got
def task_detail(task: AITask) -> dict:
    target = task.target
    sections = []
    if isinstance(target, JobPost):
        for section in target.sections.prefetch_related("elements"):
            rows = list(section.elements.all())
            sections.append(
                {
                    "label": section.label,
                    "state": section.match_state,
                    "error": section.match_error,
                    "matched_at": section.matched_at,
                    "rows": len(rows),
                    "evaluated": sum(1 for row in rows if row.match_status),
                    "matched": section.is_matched_section,
                }
            )

    timeline = [("Queued", task.queued_at)]
    if task.started_at:
        timeline.append(("A worker picked it up", task.started_at))
    if not task.is_terminal:
        timeline.append(("Last progress", task.updated_at))
    if task.finished_at:
        timeline.append((task.get_state_display(), task.finished_at))

    url = ""
    if target is not None and hasattr(target, "get_absolute_url"):
        url = target.get_absolute_url()
    elif isinstance(target, ResumeImport):
        url = reverse("resume:review", args=[target.pk])

    history = AITask.objects.filter(
        content_type=task.content_type, object_id=task.object_id
    ).exclude(pk=task.pk).order_by("-queued_at")[:10]

    return {
        "task": task,
        "target": target,
        "target_url": url,
        "target_state": getattr(target, "status", None) or getattr(target, "state", ""),
        "sections": sections,
        "timeline": timeline,
        "history": history,
        "stalled_after": AITask.STALLED_AFTER_SECONDS,
    }


#: How long the worker inspection waits for replies.
WORKER_INSPECT_TIMEOUT = 1.0


# UC-08.9 — step 2: what the workers are doing right now
def worker_report() -> dict:
    """Ask the Celery workers what they are running and holding, and count what
    is still waiting in the broker. Never raises: when the answer cannot be had
    (tasks run inline in development, the broker is down, no worker replied) it
    says why instead."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return {
            "available": False,
            "reason": "Tasks run inside the web process (eager mode), so there are no workers to inspect.",
        }
    try:
        from config.celery import app

        inspector = app.control.inspect(timeout=WORKER_INSPECT_TIMEOUT)
        active = inspector.active()
        # Only worth a second round trip if somebody answered the first.
        reserved = (inspector.reserved() or {}) if active else {}
    except Exception as exc:
        return {"available": False, "reason": f"Could not reach the broker: {exc}"}
    if not active:
        return {
            "available": False,
            "reason": "No worker answered. Is one running (celery -A config worker)?",
            "waiting_in_broker": _broker_backlog(),
        }

    tracked = {
        task.celery_task_id: task
        for task in AITask.objects.filter(
            celery_task_id__in=[
                running["id"] for running_tasks in active.values() for running in running_tasks
            ]
        ).select_related("user")
    }
    now = timezone.now().timestamp()
    workers = []
    for name, running_tasks in sorted(active.items()):
        workers.append(
            {
                "name": name,
                "reserved": len(reserved.get(name, [])),
                "running": [
                    {
                        "id": running["id"],
                        "task": running["name"].rsplit(".", 1)[-1],
                        "started": running.get("time_start"),
                        "seconds": (
                            max(0, int(now - running["time_start"]))
                            if running.get("time_start")
                            else None
                        ),
                        "args": str(running.get("args", ""))[:120],
                        "ai_task": tracked.get(running["id"]),
                    }
                    for running in running_tasks
                ],
            }
        )
    return {"available": True, "workers": workers, "waiting_in_broker": _broker_backlog()}


def _broker_backlog():
    """Messages waiting in the broker's default queue, or None if unknown."""
    try:
        import redis

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1)
        return int(client.llen("celery"))
    except Exception:
        return None


# UC-08.9 — step 4: the queue as a CSV
def export_tasks(request, params):
    queryset = search_tasks(params)
    audit.log(
        request, audit.EXPORT_DOWNLOADED,
        summary=f"AI queue CSV ({queryset.count()} rows).",
    )
    return exports.stream_csv(
        exports.timestamped("ai-tasks"), exports.TASK_HEADER, exports.task_rows(queryset)
    )


# UC-08.9 — step 3: retry and cancel address a job by its id
def ai_tasks():
    return AITask.objects.all()


# UC-08.9 — step 3: re-run a failed job on the customer's behalf
def retry_task(request, task: AITask) -> None:
    """Dispatch goes through the same `enqueue_*` helpers the product uses, so a
    retry from here is indistinguishable from the customer pressing the button —
    no second code path to keep correct. Raises `PreconditionFailed` when what
    the job was about is gone, and `ServiceError` when it could not be queued."""
    target = task.target
    if target is None:
        raise PreconditionFailed("The object this job was about no longer exists.")

    try:
        _requeue(task, target)
    except Exception as exc:
        raise ServiceError(f"Could not re-queue: {exc}") from exc

    audit.log(
        request, audit.TASK_RETRIED, target=task,
        summary=f"{task.get_kind_display()} re-queued for {task.user.email}.",
        kind=task.kind,
    )


def _requeue(task, target):
    from jobs.tasks import enqueue_full_match, enqueue_job_analysis
    from resume.tasks import enqueue_resume_analysis, enqueue_tailored_resume

    if task.kind == AITask.JOB_ANALYSIS:
        return enqueue_job_analysis(target)
    if task.kind == AITask.JOB_MATCH:
        return enqueue_full_match(target)
    if task.kind == AITask.RESUME_IMPORT:
        return enqueue_resume_analysis(target)
    if task.kind == AITask.TAILORED_RESUME:
        # The tailored-resume pipeline is keyed on the job, not the draft.
        return enqueue_tailored_resume(target.job)
    raise ValueError(f"No retry path for {task.kind}")


# UC-08.9 — stopping a job that is stuck
def cancel_task(request, task: AITask) -> bool:
    """Close the record of a job that is still open; False when it had already
    finished. Only the record is closed — a Celery worker already inside the task
    keeps running until its time limit. That is honest: revoking mid-flight would
    leave half-written analysis behind."""
    if task.is_terminal:
        return False
    task.state = AITask.CANCELED
    task.finished_at = timezone.now()
    task.save(update_fields=["state", "finished_at", "updated_at"])
    audit.log(
        request, audit.TASK_CANCELED, target=task,
        summary=f"{task.get_kind_display()} canceled.", kind=task.kind,
    )
    return True


# ---------------------------------------------------------------------------
# UC-08.10 — Immutable Append-Only Audit Logging & Retention
# ---------------------------------------------------------------------------
# UC-08.10 — step 3: the trail, filtered by action, actor, free text and
# whether it happened during an impersonation
def search_audit(params):
    queryset = AuditLog.objects.select_related("actor")
    action = params.get("action", "")
    if action:
        queryset = queryset.filter(action=action)
    actor = params.get("actor", "")
    if actor.isdigit():
        queryset = queryset.filter(actor_id=int(actor))
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(actor_email__icontains=query)
            | Q(target_repr__icontains=query)
            | Q(summary__icontains=query)
        )
    impersonated = params.get("impersonated", "")
    if impersonated == "1":
        queryset = queryset.filter(while_impersonating=True)
    return queryset


# UC-08.10 — step 3: who appears in the trail
def audit_actors():
    return User.objects.filter(staff_actions__isnull=False).distinct()


# UC-08.10 — step 3: the trail as a CSV. Exporting the audit log is itself
# audited — it has to be: "who took a copy of the trail" is exactly the question
# the trail is kept for.
def export_audit(request, params):
    queryset = search_audit(params)
    audit.log(
        request, audit.EXPORT_DOWNLOADED,
        summary=f"Audit log CSV ({queryset.count()} rows).",
    )
    return exports.stream_csv(
        exports.timestamped("audit-log"), exports.AUDIT_HEADER, exports.audit_rows(queryset)
    )


# UC-08.10 — step 4: the retention policy
def prune_audit_log(days: int | None = None, *, dry_run: bool = False) -> tuple:
    """Delete audit entries older than `days` (default: the `audit_retention_days`
    setting), or only count them with `dry_run`. Returns `(count, days)`.

    Entries go through the queryset rather than one at a time: the model refuses
    individual deletes on purpose, so that nothing in a view can quietly remove a
    single inconvenient row.
    """
    days = days or int(runtime_settings.get("audit_retention_days"))
    cutoff = timezone.now() - timedelta(days=days)
    stale = AuditLog.objects.filter(created_at__lt=cutoff)
    count = stale.count()
    if not dry_run:
        stale.delete()
    return count, days


# ---------------------------------------------------------------------------
# UC-08.11 — GDPR Art. 20 JSON Portability & Operator-Initiated Account Erasure
# ---------------------------------------------------------------------------
# UC-08.11 — Main Success Scenario (Data Portability Export), steps 2-4:
# everything held about one person, as JSON
def export_account_data(request, account):
    audit.log(
        request,
        audit.USER_EXPORTED,
        target=account,
        summary="Account data export downloaded.",
    )
    return exports.account_export_response(account)


# UC-08.11 — Main Success Scenario (Operator-Initiated Erasure), step 2: what the
# confirmation page warns about
def deletion_preview(account, operator) -> dict:
    return {
        "profile_count": account.profiles.count(),
        "job_post_count": JobPost.objects.filter(profile__user=account).count(),
        "blocked": account.is_superuser and not operator.is_superuser,
    }


# UC-08.11 — Main Success Scenario (Operator-Initiated Erasure), steps 3-6
def delete_account_as_operator(request, account, confirm_email: str, reason: str) -> str:
    """Erase `account` and everything belonging to it (GDPR Art. 17). Irreversible,
    so it is typed rather than clicked: the confirmation is the account's email in
    full, because a delete that is one click away from a list row eventually
    happens to the wrong account.

    Returns the deleted address. Raises `Refused` for a superuser's account
    unless you are one, and `PreconditionFailed` when the address does not match.
    """
    if account.is_superuser and not request.user.is_superuser:
        raise Refused("Only a superuser may delete a superuser account.")
    if confirm_email.strip().lower() != account.email.lower():
        raise PreconditionFailed("The email address did not match. Nothing was deleted.")

    email = account.email
    # Audited *before* the delete: the row records a user that is about to stop
    # existing, and `actor` is SET_NULL rather than cascaded, so the entry
    # outlives both accounts.
    audit.log(
        request,
        audit.USER_DELETED,
        target=account,
        summary=f"Account {email} and all of its data deleted.",
        email=email,
        reason=reason[:200],
    )
    account.delete()
    return email
