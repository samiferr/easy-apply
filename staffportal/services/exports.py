"""CSV and JSON exports.

Two very different jobs share this module:

* **Operational CSVs** (accounts, subscriptions, audit trail, queue) — the
  export an operator reaches for when a question needs a spreadsheet. They
  stream, so exporting 200k rows does not build a 200k-row string in memory
  first.
* **The account data export** — a machine-readable copy of everything held
  about one person, which GDPR Art. 20 (and CCPA) obliges an operator to be
  able to produce. Doing it by hand across nine tables is how a 30-day legal
  deadline gets missed.
"""

import csv
import json
from datetime import datetime

from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

from accounts.models import Profile
from core.models import AITask
from jobs.models import JobPost
from resume.models import ResumeImport, TailoredResume

from ..models import Subscription, SupportNote, UsageRecord


class _Echo:
    """A file-like object whose `write` returns the line, so `csv.writer` can
    feed a streaming response instead of a buffer."""

    def write(self, value):
        return value


def _stamp(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
    return "" if value is None else value


def stream_csv(filename: str, header: list[str], rows) -> StreamingHttpResponse:
    writer = csv.writer(_Echo())

    def generator():
        yield writer.writerow(header)
        for row in rows:
            yield writer.writerow([_stamp(value) for value in row])

    response = StreamingHttpResponse(generator(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def timestamped(prefix: str, extension: str = "csv") -> str:
    return f"{prefix}-{timezone.localdate():%Y%m%d}.{extension}"


# --- Operational exports ---------------------------------------------------
USER_HEADER = [
    "id", "email", "first_name", "last_name", "is_active", "is_staff",
    "date_joined", "last_login", "last_seen_at", "profiles", "job_posts",
    "plan", "subscription_status",
]


def user_rows(queryset):
    queryset = queryset.select_related("subscription__plan")
    for user in queryset.iterator(chunk_size=500):
        subscription = getattr(user, "subscription", None)
        yield [
            user.pk,
            user.email,
            user.first_name,
            user.last_name,
            user.is_active,
            user.is_staff,
            user.date_joined,
            user.last_login,
            user.last_seen_at,
            getattr(user, "profile_count", None) if hasattr(user, "profile_count")
            else user.profiles.count(),
            getattr(user, "job_post_count", None) if hasattr(user, "job_post_count")
            else JobPost.objects.filter(profile__user=user).count(),
            subscription.plan.name if subscription else "",
            subscription.status if subscription else "",
        ]


SUBSCRIPTION_HEADER = [
    "id", "email", "plan", "status", "price_cents", "currency", "interval",
    "started_at", "trial_ends_at", "current_period_start", "current_period_end",
    "cancel_at_period_end", "canceled_at", "external_customer_id",
]


def subscription_rows(queryset):
    for sub in queryset.select_related("user", "plan").iterator(chunk_size=500):
        yield [
            sub.pk, sub.user.email, sub.plan.name, sub.status,
            sub.plan.price_cents, sub.plan.currency, sub.plan.interval,
            sub.started_at, sub.trial_ends_at, sub.current_period_start,
            sub.current_period_end, sub.cancel_at_period_end, sub.canceled_at,
            sub.external_customer_id,
        ]


AUDIT_HEADER = [
    "created_at", "actor_email", "action", "target_type", "target_id",
    "target_repr", "summary", "while_impersonating", "ip_address", "metadata",
]


def audit_rows(queryset):
    for entry in queryset.iterator(chunk_size=500):
        yield [
            entry.created_at, entry.actor_email, entry.action, entry.target_type,
            entry.target_id, entry.target_repr, entry.summary,
            entry.while_impersonating, entry.ip_address,
            json.dumps(entry.metadata, ensure_ascii=False),
        ]


TASK_HEADER = [
    "id", "email", "kind", "state", "attempts", "queued_at", "started_at",
    "finished_at", "duration_seconds", "error_message",
]


def task_rows(queryset):
    for task in queryset.select_related("user").iterator(chunk_size=500):
        duration = ""
        if task.started_at and task.finished_at:
            duration = round((task.finished_at - task.started_at).total_seconds(), 1)
        yield [
            task.pk,
            task.user.email if task.user_id else "",
            task.kind, task.state, task.attempts, task.queued_at,
            task.started_at, task.finished_at, duration,
            task.error_message[:200],
        ]


# --- Per-account data export (GDPR Art. 20) --------------------------------
def account_export(user) -> dict:
    """Everything this product holds about one account, as plain JSON.

    Deliberately exhaustive rather than tidy: the obligation is to hand over the
    data, and a partial export that looks complete is worse than none.
    """
    profiles = Profile.objects.filter(user=user)
    subscription = Subscription.objects.filter(user=user).select_related("plan").first()

    return {
        "exported_at": timezone.now().isoformat(),
        "account": {
            "id": user.pk,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "date_joined": user.date_joined.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
        },
        "subscription": (
            {
                "plan": subscription.plan.name,
                "status": subscription.status,
                "started_at": subscription.started_at.isoformat(),
                "current_period_start": subscription.current_period_start.isoformat(),
                "current_period_end": (
                    subscription.current_period_end.isoformat()
                    if subscription.current_period_end
                    else None
                ),
            }
            if subscription
            else None
        ),
        "usage": [
            {
                "metric": record.metric,
                "period_start": record.period_start.isoformat(),
                "period_end": record.period_end.isoformat(),
                "count": record.count,
            }
            for record in UsageRecord.objects.filter(user=user)
        ],
        "profiles": [
            {
                "id": profile.pk,
                "name": profile.name,
                "language": profile.language,
                "headline": profile.headline,
                "phone": profile.phone,
                "location": profile.location,
                "bio": profile.bio,
                "links": {
                    "linkedin": profile.linkedin_url,
                    "portfolio": profile.portfolio_url,
                    "github": profile.github_url,
                },
                "created_at": profile.created_at.isoformat(),
                "skills": [
                    {"name": s.name, "category": s.category.name, "level": s.level}
                    for s in profile.skills.select_related("category")
                ],
                "languages": [
                    {"language": ul.language.name, "proficiency": ul.proficiency}
                    for ul in profile.languages.select_related("language")
                ],
                "experiences": [
                    {
                        "job_title": e.job_title,
                        "company": e.company,
                        "location": e.location,
                        "employment_type": e.employment_type,
                        "start_date": e.start_date.isoformat() if e.start_date else None,
                        "end_date": e.end_date.isoformat() if e.end_date else None,
                        "is_current": e.is_current,
                        "highlights": [h.text for h in e.highlights.all()],
                    }
                    for e in profile.experiences.prefetch_related("highlights")
                ],
                "degrees": [
                    {
                        "school": d.school,
                        "degree": d.degree,
                        "field_of_study": d.field_of_study,
                        "start_date": d.start_date.isoformat() if d.start_date else None,
                        "end_date": d.end_date.isoformat() if d.end_date else None,
                        "grade": d.grade,
                        "description": d.description,
                    }
                    for d in profile.degrees.all()
                ],
                "certificates": [
                    {
                        "name": c.name,
                        "issuing_organization": c.issuing_organization,
                        "issue_date": c.issue_date.isoformat() if c.issue_date else None,
                        "credential_id": c.credential_id,
                        "credential_url": c.credential_url,
                    }
                    for c in profile.certificates.all()
                ],
            }
            for profile in profiles
        ],
        "job_posts": [
            {
                "id": job.pk,
                "title": job.title,
                "company": job.company_name,
                "status": job.status,
                "created_at": job.created_at.isoformat(),
                "description_text": job.description_text,
            }
            for job in JobPost.objects.filter(profile__in=profiles)
        ],
        "tailored_resumes": [
            {
                "job": resume.job.title,
                "state": resume.state,
                "markdown": resume.markdown,
                "created_at": resume.created_at.isoformat(),
            }
            for resume in TailoredResume.objects.filter(profile__in=profiles).select_related("job")
        ],
        "resume_imports": [
            {
                "filename": item.original_filename,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in ResumeImport.objects.filter(profile__in=profiles)
        ],
        "ai_tasks": [
            {
                "kind": task.kind,
                "state": task.state,
                "queued_at": task.queued_at.isoformat(),
                "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            }
            for task in AITask.objects.filter(user=user)
        ],
        # Support notes are internal, about the customer rather than authored by
        # them — but they are personal data held about an identified person, so
        # a subject access request covers them.
        "support_notes": [
            {"created_at": note.created_at.isoformat(), "body": note.body}
            for note in SupportNote.objects.filter(user=user)
        ],
    }


def account_export_response(user) -> HttpResponse:
    payload = json.dumps(account_export(user), indent=2, ensure_ascii=False)
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    filename = f"account-{user.pk}-export-{timezone.localdate():%Y%m%d}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
