"""Evaluating feature flags.

Evaluation is deterministic: the bucket a user falls into is a hash of the flag
key and the user id, so a 10% rollout is the *same* 10% on every request and on
every process. Bucketing on something random — a session, the clock — is how a
"gradual rollout" turns into a feature that flickers on and off for everyone.

A flag that does not exist is off. Failing closed means deleting a flag row
retires the feature rather than releasing it to everyone.
"""

import hashlib

from ..models import FeatureFlag, Subscription


def bucket(key: str, user_id: int) -> int:
    """A stable 0–99 bucket for this (flag, user) pair."""
    digest = hashlib.sha256(f"{key}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def _evaluate(flag: FeatureFlag, user) -> bool:
    anonymous = user is None or not getattr(user, "is_authenticated", False)
    if anonymous:
        # Nothing account-shaped applies: only a blanket "on" reaches a visitor.
        return flag.state == FeatureFlag.ON

    # Explicit per-account overrides win over everything — that is what they are
    # for: putting one customer on a feature to reproduce their bug report.
    if flag.users.filter(pk=user.pk).exists():
        return True

    plan_ids = list(flag.plans.values_list("id", flat=True))
    if plan_ids:
        entitled = Subscription.objects.filter(
            user=user,
            plan_id__in=plan_ids,
            status__in=Subscription.ENTITLED_STATUSES,
        ).exists()
        if entitled:
            return True

    if flag.state == FeatureFlag.ON:
        return True
    if flag.state == FeatureFlag.OFF:
        return False
    if flag.state == FeatureFlag.STAFF:
        return bool(user.is_staff)
    if flag.state == FeatureFlag.PERCENT:
        return bucket(flag.key, user.pk) < flag.percentage
    return False


def is_enabled(key: str, user=None) -> bool:
    flag = FeatureFlag.objects.filter(key=key).first()
    if flag is None:
        return False
    return _evaluate(flag, user)


def enabled_for(user) -> set[str]:
    """Every flag key that is on for this user — for the portal's user detail
    screen, so support can see what the customer is actually running."""
    return {flag.key for flag in FeatureFlag.objects.all() if _evaluate(flag, user)}
