"""The numbers on the portal's overview screen.

Everything here is aggregated in the database — no Python loops over rows — and
every series is bounded by a day window, so the dashboard costs the same on the
first customer and the hundred-thousandth.

The choice of metrics is deliberate. Signups and totals say how big the product
is; activation, retention and churn say whether it works. A SaaS dashboard that
only shows totals always goes up and to the right, including on the day the
product stops being used.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.models import Profile
from core.models import AITask
from jobs.models import JobPost
from resume.models import ResumeImport, TailoredResume

from ..models import Announcement, FeatureFlag, Plan, Subscription

User = get_user_model()


def _money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def daily_series(queryset, field: str, *, days: int = 30, label: str = "") -> dict:
    """A day-by-day bar chart, rendered server-side like the rest of this app.

    Returns the same shape `core.views` uses for the jobs chart, so the portal's
    chart partial and the customer-facing one stay interchangeable.
    """
    today = timezone.localdate()
    first = today - timedelta(days=days - 1)
    rows = (
        queryset.filter(**{f"{field}__date__gte": first})
        .annotate(day=TruncDate(field))
        .values("day")
        .annotate(count=Count("id"))
    )
    counts = {row["day"]: row["count"] for row in rows if row["day"]}
    peak = max(counts.values()) if counts else 0

    bars = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        count = counts.get(day, 0)
        bars.append(
            {
                "day": day,
                "number": day.day,
                "count": count,
                "percent": round((count / peak) * 100) if peak else 0,
                "is_today": day == today,
            }
        )
    return {
        "label": label,
        "bars": bars,
        "peak": peak,
        "total": sum(counts.values()),
        "days": days,
        "has_data": bool(counts),
    }


def growth() -> dict:
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    two_months_ago = now - timedelta(days=60)

    users = User.objects.all()
    last_30 = users.filter(date_joined__gte=month_ago).count()
    previous_30 = users.filter(
        date_joined__gte=two_months_ago, date_joined__lt=month_ago
    ).count()

    return {
        "total": users.count(),
        "active": users.filter(is_active=True).count(),
        "suspended": users.filter(is_active=False).count(),
        "staff": users.filter(is_staff=True).count(),
        "new_24h": users.filter(date_joined__gte=day_ago).count(),
        "new_7d": users.filter(date_joined__gte=week_ago).count(),
        "new_30d": last_30,
        # The direction matters more than the number; a bare "+37 this month"
        # is not a trend.
        "growth_percent": (
            round(((last_30 - previous_30) / previous_30) * 100) if previous_30 else None
        ),
    }


def engagement() -> dict:
    """Daily / weekly / monthly actives, from `User.last_seen_at`.

    DAU/MAU ("stickiness") is the one ratio worth putting on a dashboard: it
    answers whether the people who signed up are coming back, which no total
    ever does.
    """
    now = timezone.now()
    seen = User.objects.filter(last_seen_at__isnull=False)
    dau = seen.filter(last_seen_at__gte=now - timedelta(days=1)).count()
    wau = seen.filter(last_seen_at__gte=now - timedelta(days=7)).count()
    mau = seen.filter(last_seen_at__gte=now - timedelta(days=30)).count()
    return {
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "stickiness": round((dau / mau) * 100) if mau else 0,
    }


def revenue() -> dict:
    """MRR, ARR and the shape of the subscriber base.

    Trials are counted separately rather than folded into MRR — revenue that
    has not been charged yet is a forecast, not revenue.
    """
    subscriptions = Subscription.objects.select_related("plan")
    mrr = sum(sub.mrr_cents for sub in subscriptions.filter(
        status__in=[Subscription.ACTIVE, Subscription.PAST_DUE]
    ))
    paying = subscriptions.filter(
        status__in=[Subscription.ACTIVE, Subscription.PAST_DUE], plan__price_cents__gt=0
    ).count()
    free = subscriptions.filter(
        status__in=Subscription.ENTITLED_STATUSES, plan__price_cents=0
    ).count()
    trialing = subscriptions.filter(status=Subscription.TRIALING).count()
    entitled = subscriptions.filter(status__in=Subscription.ENTITLED_STATUSES).count()

    month_ago = timezone.now() - timedelta(days=30)
    churned_30d = subscriptions.filter(
        status__in=[Subscription.CANCELED, Subscription.EXPIRED], canceled_at__gte=month_ago
    ).count()
    base = entitled + churned_30d

    return {
        "mrr_cents": mrr,
        "mrr_display": _money(mrr),
        "arr_display": _money(mrr * 12),
        "paying": paying,
        "free": free,
        "trialing": trialing,
        "past_due": subscriptions.filter(status=Subscription.PAST_DUE).count(),
        "entitled": entitled,
        # Average revenue per paying account — the number that says whether
        # pricing works, as opposed to how many people showed up.
        "arpa_display": _money(round(mrr / paying)) if paying else _money(0),
        "churn_percent": round((churned_30d / base) * 100, 1) if base else 0.0,
        "churned_30d": churned_30d,
    }


def plan_breakdown() -> list[dict]:
    rows = (
        Subscription.objects.filter(status__in=Subscription.ENTITLED_STATUSES)
        .values("plan__id", "plan__name", "plan__price_cents", "plan__interval")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    total = sum(row["count"] for row in rows) or 1
    breakdown = []
    for row in rows:
        monthly = (
            round(row["plan__price_cents"] / 12)
            if row["plan__interval"] == Plan.YEAR
            else row["plan__price_cents"]
        )
        breakdown.append(
            {
                "plan_id": row["plan__id"],
                "name": row["plan__name"],
                "count": row["count"],
                "percent": round((row["count"] / total) * 100),
                "mrr_display": _money(monthly * row["count"]),
            }
        )
    return breakdown


def product_usage() -> dict:
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    return {
        "profiles": Profile.objects.count(),
        "job_posts": JobPost.objects.count(),
        "job_posts_7d": JobPost.objects.filter(created_at__gte=week_ago).count(),
        "tailored_resumes": TailoredResume.objects.count(),
        "resume_imports": ResumeImport.objects.count(),
        "analyses_24h": JobPost.objects.filter(created_at__gte=day_ago).count(),
    }


def ai_health(days: int = 7) -> dict:
    """How the AI pipeline is actually doing.

    Success rate over a window, not a lifetime total: a provider that started
    failing this morning is invisible in a lifetime average.
    """
    since = timezone.now() - timedelta(days=days)
    window = AITask.objects.filter(queued_at__gte=since)
    counts = window.aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(state=AITask.DONE)),
        failed=Count("id", filter=Q(state=AITask.FAILED)),
        canceled=Count("id", filter=Q(state=AITask.CANCELED)),
    )
    finished = counts["done"] + counts["failed"]
    running = AITask.objects.filter(state__in=[AITask.QUEUED, AITask.RUNNING]).count()

    by_kind = list(
        window.values("kind")
        .annotate(
            total=Count("id"),
            failed=Count("id", filter=Q(state=AITask.FAILED)),
        )
        .order_by("-total")
    )
    kind_labels = dict(AITask.KIND_CHOICES)
    for row in by_kind:
        row["label"] = str(kind_labels.get(row["kind"], row["kind"]))
        row["failure_percent"] = (
            round((row["failed"] / row["total"]) * 100) if row["total"] else 0
        )

    return {
        "days": days,
        "total": counts["total"],
        "failed": counts["failed"],
        "running": running,
        "success_percent": round((counts["done"] / finished) * 100) if finished else 100,
        "by_kind": by_kind,
        "stuck": AITask.objects.filter(
            state=AITask.RUNNING, updated_at__lt=timezone.now() - timedelta(hours=1)
        ).count(),
    }


def activation(days: int = 30) -> dict:
    """The only funnel that matters early: did the account do the thing?

    "Signed up" is not a customer. An account that has analyzed a job post has
    reached the product's core action; the gap between the two is where a SaaS
    quietly leaks its acquisition spend.
    """
    since = timezone.now() - timedelta(days=days)
    cohort = User.objects.filter(date_joined__gte=since)
    signed_up = cohort.count()
    with_profile_content = cohort.filter(profiles__job_posts__isnull=False).distinct().count()
    with_resume = cohort.filter(profiles__job_posts__tailored_resume__isnull=False).distinct().count()
    return {
        "days": days,
        "signed_up": signed_up,
        "analyzed": with_profile_content,
        "generated": with_resume,
        "analyzed_percent": round((with_profile_content / signed_up) * 100) if signed_up else 0,
        "generated_percent": round((with_resume / signed_up) * 100) if signed_up else 0,
    }


def attention() -> dict:
    """Things an operator should look at now, counted for the dashboard's
    "needs attention" strip."""
    return {
        "failed_tasks_24h": AITask.objects.filter(
            state=AITask.FAILED, finished_at__gte=timezone.now() - timedelta(days=1)
        ).count(),
        "past_due": Subscription.objects.filter(status=Subscription.PAST_DUE).count(),
        "suspended_users": User.objects.filter(is_active=False).count(),
        "live_announcements": Announcement.objects.live().count(),
        "flags_on": FeatureFlag.objects.exclude(state=FeatureFlag.OFF).count(),
    }


def overview(days: int = 30) -> dict:
    return {
        "growth": growth(),
        "engagement": engagement(),
        "revenue": revenue(),
        "plans": plan_breakdown(),
        "usage": product_usage(),
        "ai": ai_health(),
        "activation": activation(days),
        "attention": attention(),
        "signups_chart": daily_series(
            User.objects.all(), "date_joined", days=days, label="Sign-ups"
        ),
        "analyses_chart": daily_series(
            JobPost.objects.all(), "created_at", days=days, label="Job analyses"
        ),
    }
