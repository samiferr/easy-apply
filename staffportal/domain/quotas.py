"""Plan allowances, what has been used against them, and the one function the
product calls before starting metered work.

Two switches gate every check, and both live in the portal:

* `ai_features_enabled` — the kill switch. Off means no AI work starts at all,
  whatever anyone's plan says.
* `enforce_quotas` — off by default, so plans can be modelled, reviewed and
  corrected before they start refusing work. Turning it on is a deliberate act.

With both untouched the product behaves exactly as it did before this app
existed. That is on purpose: shipping enforcement dark and enabling it when the
numbers read right is cheaper than discovering a wrong limit in production.
"""

from dataclasses import dataclass

from django.db.models import F
from django.utils.translation import gettext as _

from ..models import UsageMetric, UsageRecord
from . import runtime_settings, subscriptions


@dataclass(frozen=True)
class Allowance:
    metric: str
    label: str
    limit: int | None  # None = unlimited
    used: int

    @property
    def unlimited(self) -> bool:
        return self.limit is None

    @property
    def remaining(self) -> int | None:
        if self.unlimited:
            return None
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return not self.unlimited and self.used >= self.limit

    @property
    def percent(self) -> int:
        """For the meter in the UI. Unlimited reads as 0 — there is no bar to fill."""
        if self.unlimited or not self.limit:
            return 0
        return min(100, round((self.used / self.limit) * 100))


def enforcement_enabled() -> bool:
    return bool(runtime_settings.get("enforce_quotas"))


def ai_enabled() -> bool:
    return bool(runtime_settings.get("ai_features_enabled"))


def allowance(user, metric: str) -> Allowance:
    label = UsageMetric(metric).label
    subscription = subscriptions.ensure_subscription(user)
    if subscription is None:
        # No plans configured yet — nothing is limited.
        return Allowance(metric=metric, label=label, limit=None, used=0)

    start, end = subscriptions.current_period(subscription)
    record = UsageRecord.objects.filter(
        user=user, metric=metric, period_start=start
    ).first()
    return Allowance(
        metric=metric,
        label=label,
        limit=subscription.plan.quota_for(metric),
        used=record.count if record else 0,
    )


def summary(user) -> list[Allowance]:
    return [allowance(user, metric) for metric, _label in UsageMetric.choices]


def profile_limit(user) -> tuple[int | None, int]:
    """(limit, used) for workspaces, which are a ceiling rather than a meter."""
    from accounts.models import Profile

    used = Profile.objects.filter(user=user).count()
    subscription = subscriptions.ensure_subscription(user)
    limit = subscription.plan.max_profiles if subscription else None
    return limit, used


def consume(user, metric: str, amount: int = 1) -> None:
    """Record metered work as started.

    Counted on dispatch, not on success: an analysis that reaches the AI
    provider has cost real money whether or not the answer came back usable,
    and a retry loop that costs nothing is an invitation.
    """
    subscription = subscriptions.ensure_subscription(user)
    if subscription is None:
        return
    start, end = subscriptions.current_period(subscription)
    record, created = UsageRecord.objects.get_or_create(
        user=user,
        metric=metric,
        period_start=start,
        defaults={"period_end": end, "count": amount},
    )
    if not created:
        # F() rather than read-modify-write: the Celery worker and the web
        # process both write this row.
        UsageRecord.objects.filter(pk=record.pk).update(count=F("count") + amount)


def ai_unavailable_message() -> str | None:
    """The kill switch on its own.

    Used by the paths that are follow-ups to work already paid for — re-running
    one section's match, retrying a failed element — where the account should
    not be charged a second time but the switch still has to hold.
    """
    if ai_enabled():
        return None
    return _(
        "AI features are temporarily unavailable while we carry out maintenance. "
        "Please try again shortly."
    )


def blocked_message(user, metric: str) -> str | None:
    """The reason this account may not start `metric` right now, or None.

    One call site, one sentence to show the user. Both the AI kill switch and
    plan enforcement answer through here so no caller has to remember both.
    """
    unavailable = ai_unavailable_message()
    if unavailable:
        return unavailable
    if not enforcement_enabled():
        return None

    current = allowance(user, metric)
    if current.limit == 0:
        return _("Your plan doesn't include this feature. Upgrade to use it.")
    if current.exhausted:
        return _(
            "You've used all %(limit)s of this month's %(label)s. Your allowance "
            "resets at the start of your next billing period."
        ) % {"limit": current.limit, "label": current.label.lower()}
    return None


def profile_blocked_message(user) -> str | None:
    if not enforcement_enabled():
        return None
    limit, used = profile_limit(user)
    if limit is not None and used >= limit:
        return _(
            "Your plan allows %(limit)s profile(s). Delete one, or upgrade, to add another."
        ) % {"limit": limit}
    return None
