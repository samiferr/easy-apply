"""Resolving and moving a customer's subscription.

Every account has exactly one `Subscription` row, created at registration, so
no code path anywhere has to handle "user without a subscription". When plans
have not been seeded yet (a fresh database, before `manage.py seed_saas`) the
helpers return None and the callers treat that as "no limits configured".
"""

from calendar import monthrange
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Plan, Subscription


def add_month(moment):
    """One month on, clamped to the length of the target month.

    Anchoring the period to the signup day is what customers expect from a
    monthly plan; a fixed 30 days drifts a whole day every four months.
    """
    year = moment.year + (moment.month // 12)
    month = moment.month % 12 + 1
    day = min(moment.day, monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def default_plan() -> Plan | None:
    return Plan.objects.filter(is_default=True, is_active=True).first()


def ensure_subscription(user) -> Subscription | None:
    """This account's subscription, creating it on the default plan if needed."""
    subscription = Subscription.objects.filter(user=user).select_related("plan").first()
    if subscription is not None:
        return subscription

    plan = default_plan()
    if plan is None:
        return None

    now = timezone.now()
    try:
        with transaction.atomic():
            return Subscription.objects.create(
                user=user,
                plan=plan,
                status=Subscription.TRIALING if plan.trial_days else Subscription.ACTIVE,
                trial_ends_at=now + timedelta(days=plan.trial_days) if plan.trial_days else None,
                started_at=now,
                current_period_start=now,
                current_period_end=add_month(now),
            )
    except IntegrityError:
        # Two requests raced to provision the same account.
        return Subscription.objects.filter(user=user).select_related("plan").first()


def current_period(subscription: Subscription) -> tuple:
    """The window usage is counted against, rolled forward if it has lapsed.

    The roll happens lazily on read rather than in a nightly job: a customer who
    does not come back for three months should still find a fresh allowance
    waiting, without anything having had to run while they were away.
    """
    now = timezone.now()
    start = subscription.current_period_start
    end = subscription.current_period_end or add_month(start)

    if end > now:
        return start, end

    while end <= now:
        start, end = end, add_month(end)

    Subscription.objects.filter(pk=subscription.pk).update(
        current_period_start=start, current_period_end=end, updated_at=now
    )
    subscription.current_period_start = start
    subscription.current_period_end = end
    return start, end


def change_plan(subscription: Subscription, plan: Plan, *, status: str | None = None):
    """Move an account onto another plan, restarting the metering window.

    Restarting matters: moving up mid-month should hand over the new allowance
    immediately rather than making the customer wait out a period they already
    paid more for.
    """
    now = timezone.now()
    subscription.plan = plan
    if status:
        subscription.status = status
    subscription.current_period_start = now
    subscription.current_period_end = add_month(now)
    subscription.save(
        update_fields=[
            "plan", "status", "current_period_start", "current_period_end", "updated_at",
        ]
    )
    return subscription
