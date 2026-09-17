"""The records behind the staff portal — the SaaS plumbing this product needs
once it is sold rather than self-hosted.

Five concerns live here, deliberately in one app so that "everything an
operator can change" has one place to look:

* **Who may operate it** — `StaffMember` puts a role on a staff account, so
  "can read the dashboard" and "can delete a customer" are not the same grant.
* **What a customer is entitled to** — `Plan`, `Subscription`, `UsageRecord`.
* **What is switched on** — `FeatureFlag`, `SystemSetting`, `Announcement`.
* **What was done, by whom** — `AuditLog`, `ImpersonationSession`, `SupportNote`.

Nothing here is written by the user-facing app except `UsageRecord`, which is
incremented as metered work is started.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# Staff access
# ---------------------------------------------------------------------------
class StaffRole(models.TextChoices):
    """What a staff account may do in the portal.

    `is_staff` alone is the door; the role is what is behind it. A staff
    account with no `StaffMember` row gets `VIEWER`, so adding someone to the
    portal by mistake exposes read-only screens rather than the delete button.
    Superusers bypass roles entirely — see `services.access`.
    """

    VIEWER = "viewer", "Viewer — read-only"
    SUPPORT = "support", "Support — user actions, impersonation, notes"
    BILLING = "billing", "Billing — support, plus plans and subscriptions"
    ADMIN = "admin", "Admin — everything except superuser-only actions"


class StaffMember(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_member"
    )
    role = models.CharField(max_length=20, choices=StaffRole.choices, default=StaffRole.VIEWER)
    note = models.CharField(
        max_length=200, blank=True, help_text="Why this person has portal access."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__email"]
        verbose_name = "staff member"
        verbose_name_plural = "staff members"

    def __str__(self):
        return f"{self.user.email} ({self.get_role_display()})"


# ---------------------------------------------------------------------------
# Plans, subscriptions, usage
# ---------------------------------------------------------------------------
class UsageMetric(models.TextChoices):
    """The metered actions. Each one maps to a monthly allowance on `Plan` and
    to a counter row in `UsageRecord`.

    The labels are translated even though the portal is English-only: they are
    interpolated into the message a *customer* sees when an allowance runs out.
    """

    JOB_ANALYSIS = "job_analysis", _("Job analyses")
    TAILORED_RESUME = "tailored_resume", _("Tailored resumes")
    RESUME_IMPORT = "resume_import", _("Resume imports")


#: metric -> the `Plan` field holding its monthly allowance.
METRIC_QUOTA_FIELDS = {
    UsageMetric.JOB_ANALYSIS: "monthly_job_analyses",
    UsageMetric.TAILORED_RESUME: "monthly_tailored_resumes",
    UsageMetric.RESUME_IMPORT: "monthly_resume_imports",
}


class Plan(models.Model):
    """A price point and the allowances that come with it.

    Allowance fields are nullable and `NULL` means *unlimited* — `0` means the
    feature is not included at all. Keeping the two apart matters: a free plan
    that should not generate resumes is `0`, not "unset".
    """

    MONTH = "month"
    YEAR = "year"
    INTERVAL_CHOICES = [(MONTH, "Monthly"), (YEAR, "Yearly")]

    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=60)
    tagline = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)

    # Money is an integer number of minor units, never a float.
    price_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    interval = models.CharField(max_length=10, choices=INTERVAL_CHOICES, default=MONTH)
    trial_days = models.PositiveSmallIntegerField(default=0)

    is_active = models.BooleanField(
        default=True, help_text="Inactive plans keep their subscribers but take no new ones."
    )
    is_public = models.BooleanField(default=True, help_text="Listed on the pricing page.")
    is_default = models.BooleanField(
        default=False, help_text="The plan a new account is put on. Exactly one plan has this."
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    # Allowances. NULL = unlimited, 0 = not included.
    max_profiles = models.PositiveIntegerField(null=True, blank=True)
    monthly_job_analyses = models.PositiveIntegerField(null=True, blank=True)
    monthly_tailored_resumes = models.PositiveIntegerField(null=True, blank=True)
    monthly_resume_imports = models.PositiveIntegerField(null=True, blank=True)

    features = models.TextField(blank=True, help_text="One selling point per line.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_cents", "id"]
        constraints = [
            # A new account has to land somewhere, and it has to be one place.
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="only_one_default_plan",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def price_display(self) -> str:
        if not self.price_cents:
            return "Free"
        amount = self.price_cents / 100
        suffix = "/mo" if self.interval == self.MONTH else "/yr"
        return f"{amount:,.2f} {self.currency}{suffix}"

    @property
    def monthly_price_cents(self) -> int:
        """Normalized to a month so yearly and monthly plans can be summed into
        one MRR figure."""
        if self.interval == self.YEAR:
            return round(self.price_cents / 12)
        return self.price_cents

    @property
    def feature_list(self) -> list[str]:
        return [line.strip() for line in self.features.splitlines() if line.strip()]

    def quota_for(self, metric: str):
        """The monthly allowance for `metric`; None means unlimited."""
        field = METRIC_QUOTA_FIELDS.get(metric)
        return getattr(self, field) if field else None


class Subscription(models.Model):
    """What a single account is entitled to, right now.

    There is exactly one per user, created at registration on the default plan,
    so no code path anywhere has to handle "user without a subscription".
    `external_*` are the hooks a real payment provider (Stripe, Paddle) writes
    into later; nothing in this app bills anyone.
    """

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"
    STATUS_CHOICES = [
        (TRIALING, "Trialing"),
        (ACTIVE, "Active"),
        (PAST_DUE, "Past due"),
        (CANCELED, "Canceled"),
        (EXPIRED, "Expired"),
    ]
    #: Statuses that still grant the plan's allowances. `past_due` is included
    #: on purpose: dunning is a billing problem, not a reason to lock someone
    #: out of data they have already produced.
    ENTITLED_STATUSES = {TRIALING, ACTIVE, PAST_DUE}

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)

    started_at = models.DateTimeField(default=timezone.now)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    # The metering window. Usage is counted against `current_period_start`.
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    external_customer_id = models.CharField(max_length=100, blank=True, db_index=True)
    external_subscription_id = models.CharField(max_length=100, blank=True, db_index=True)

    notes = models.TextField(blank=True, help_text="Internal only — never shown to the customer.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "plan"])]

    def __str__(self):
        return f"{self.user.email} — {self.plan.name} ({self.get_status_display()})"

    @property
    def is_entitled(self) -> bool:
        return self.status in self.ENTITLED_STATUSES

    @property
    def is_trialing(self) -> bool:
        return self.status == self.TRIALING

    @property
    def mrr_cents(self) -> int:
        """Trials contribute nothing until they convert — counting them is how
        a revenue chart ends up lying to you."""
        if self.status not in (self.ACTIVE, self.PAST_DUE):
            return 0
        return self.plan.monthly_price_cents

    @property
    def trial_days_left(self) -> int | None:
        if not self.trial_ends_at:
            return None
        return max(0, (self.trial_ends_at - timezone.now()).days)


class UsageRecord(models.Model):
    """One counter per account, metric and billing period.

    Usage is counted here rather than derived from `core.AITask` because task
    rows are pruned on a retention schedule and a billing period must still add
    up after they are gone.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_records"
    )
    metric = models.CharField(max_length=30, choices=UsageMetric.choices)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "metric"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "metric", "period_start"], name="unique_usage_per_period"
            )
        ]
        indexes = [models.Index(fields=["metric", "period_start"])]

    def __str__(self):
        return f"{self.user_id} {self.metric} {self.count}"


# ---------------------------------------------------------------------------
# Feature flags and runtime settings
# ---------------------------------------------------------------------------
class FeatureFlag(models.Model):
    """A switch that can be flipped without a deploy.

    Evaluation is pure and deterministic (see `services.flags`): the same user
    and the same flag always land in the same bucket, so a 10% rollout does not
    reshuffle on every request.
    """

    OFF = "off"
    ON = "on"
    STAFF = "staff"
    PERCENT = "percent"
    STATE_CHOICES = [
        (OFF, "Off for everyone"),
        (ON, "On for everyone"),
        (STAFF, "Staff only"),
        (PERCENT, "Percentage rollout"),
    ]

    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=OFF)
    percentage = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="forced_feature_flags",
        help_text="Always on for these accounts, whatever the state says.",
    )
    plans = models.ManyToManyField(
        Plan,
        blank=True,
        related_name="feature_flags",
        help_text="Always on for entitled subscribers of these plans.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key

    @property
    def state_summary(self) -> str:
        if self.state == self.PERCENT:
            return f"{self.percentage}% of accounts"
        return self.get_state_display()


class SystemSetting(models.Model):
    """A typed key/value an operator can change from the portal.

    The set of keys is a registry in `services.runtime_settings`, not free
    text: a setting nothing reads is a lie in the UI, and a typo in a key is a
    silent behaviour change.
    """

    key = models.SlugField(max_length=60, unique=True)
    value = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}={self.value}"


class AnnouncementQuerySet(models.QuerySet):
    def live(self, now=None):
        now = now or timezone.now()
        return self.filter(is_active=True, starts_at__lte=now).filter(
            Q(ends_at__isnull=True) | Q(ends_at__gt=now)
        )


class Announcement(models.Model):
    """A banner shown inside the product — maintenance windows, incidents,
    release notes. Written here so saying something to every customer does not
    need a deploy."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"
    LEVEL_CHOICES = [
        (INFO, "Info"),
        (SUCCESS, "Success"),
        (WARNING, "Warning"),
        (CRITICAL, "Critical"),
    ]

    EVERYONE = "everyone"
    AUTHENTICATED = "authenticated"
    STAFF = "staff"
    AUDIENCE_CHOICES = [
        (EVERYONE, "Everyone"),
        (AUTHENTICATED, "Signed-in users"),
        (STAFF, "Staff only"),
    ]

    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default=INFO)
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default=AUTHENTICATED)
    link_url = models.URLField(blank=True)
    link_label = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)
    dismissible = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AnnouncementQuerySet.as_manager()

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return self.title

    @property
    def is_live(self) -> bool:
        now = timezone.now()
        return (
            self.is_active
            and self.starts_at <= now
            and (self.ends_at is None or self.ends_at > now)
        )


# ---------------------------------------------------------------------------
# Accountability
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    """Append-only record of everything a staff account changed.

    Denormalized `actor_email` and `target_repr` are the point: the trail has to
    stay readable after the account it talks about is deleted, which is exactly
    the case someone will come asking about.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_actions",
    )
    actor_email = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    target_repr = models.CharField(max_length=200, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # True when the action was taken from an impersonated session, which is the
    # first thing anyone reviewing a surprising change wants to know.
    while_impersonating = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "-created_at"]),
        ]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"

    def __str__(self):
        return f"{self.actor_email or 'system'} {self.action}"

    def save(self, *args, **kwargs):
        # Append-only: an audit trail that can be edited is not one.
        if self.pk is not None and not self._state.adding:
            raise ValueError("Audit log entries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Audit log entries cannot be deleted individually. "
            "Use `manage.py prune_audit_log` to apply the retention policy."
        )


class ImpersonationSession(models.Model):
    """One row per "view as customer" session.

    Separate from `AuditLog` because it has a lifetime: it opens, it expires,
    and while it is open the banner in the app is driven from it.
    """

    MANUAL = "manual"
    EXPIRED = "expired"
    LOGOUT = "logout"
    END_REASONS = [
        (MANUAL, "Ended by the operator"),
        (EXPIRED, "Timed out"),
        (LOGOUT, "Session ended"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="impersonations_started",
    )
    actor_email = models.CharField(max_length=254, blank=True)
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="impersonations_received",
    )
    target_email = models.CharField(max_length=254, blank=True)
    reason = models.CharField(max_length=200)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=20, choices=END_REASONS, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["target", "-started_at"])]

    def __str__(self):
        return f"{self.actor_email} as {self.target_email}"

    @property
    def is_open(self) -> bool:
        return self.ended_at is None and self.expires_at > timezone.now()

    def close(self, reason: str = MANUAL):
        if self.ended_at is None:
            self.ended_at = timezone.now()
            self.ended_reason = reason
            self.save(update_fields=["ended_at", "ended_reason"])


class SupportNote(models.Model):
    """An internal note on a customer account. Never shown to the customer."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author_email = models.CharField(max_length=254, blank=True)
    body = models.TextField()
    pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pinned", "-created_at"]

    def __str__(self):
        return f"Note on {self.user_id}"
