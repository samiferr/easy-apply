"""Use cases of job postings: analysing a pasted posting, matching it to the
candidate's profile, and turning a gap into a profile entry.

A posting is text the candidate pasted. It is extracted into the 13 fixed
sections of `jobs/sections.py`, and the sections that carry rows —
requirements, responsibilities, benefits — are matched row by row against only
the slice of the profile each one maps to. The work itself runs in Celery
(`jobs/tasks.py`, with the AI calls and parsing in `jobs/domain/`); the
functions below decide *whether* a request may start that work, start it, and
shape what the job page polls for. Views call these and only translate the
outcome: a `Blocked` or `PreconditionFailed` becomes a flash message, a
`Refused` becomes a JSON error.

Use cases: docs/use-cases/UC05_JOB_POSTING_MATCHING.md and
UC06_INTERACTIVE_ADD_TO_PROFILE.md.
"""

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext

from core.exceptions import Blocked, PreconditionFailed, Refused
from core.models import AITask
from resume.models import TailoredResume
from staffportal.domain import quotas
from staffportal.models import UsageMetric

from .models import JobElement, JobPost, JobSection
from .profile_targets import AddTarget, get_add_target
from .sections import SECTIONS
from .tasks import (
    enqueue_element_match,
    enqueue_full_match,
    enqueue_job_analysis,
    enqueue_section_match,
)


# ---------------------------------------------------------------------------
# UC-05 / UC-06 — the workspace boundary
# ---------------------------------------------------------------------------
# A job post, and everything hanging off it, is only ever reached through the
# profile it was analysed under: another workspace's id is a 404, not a leak.
def profile_jobs(profile):
    return JobPost.objects.filter(profile=profile)


def profile_jobs_with_sections(profile):
    """`profile_jobs` with the sections and their rows loaded in two queries, for
    the screens that show or count them."""
    return profile_jobs(profile).prefetch_related("sections__elements")


def profile_sections(profile):
    return JobSection.objects.filter(job__profile=profile)


def profile_elements(profile):
    return JobElement.objects.select_related("section", "section__job").filter(
        section__job__profile=profile
    )


# ---------------------------------------------------------------------------
# UC-05.1 — Job Posting Creation & Allowance Verification
# ---------------------------------------------------------------------------
# UC-05.1 — the list a candidate starts from (and comes back to after step 8):
# search by title, company or location, filter by analysis status. A status that
# is not one of the known ones is ignored rather than emptying the list.
def search_jobs(profile, query: str = "", status: str = ""):
    jobs = profile_jobs_with_sections(profile)
    query = query.strip()
    if query:
        jobs = jobs.filter(
            Q(title__icontains=query)
            | Q(company_name__icontains=query)
            | Q(location__icontains=query)
        )
    status = status.strip()
    if status in dict(JobPost.STATUS_CHOICES):
        jobs = jobs.filter(status=status)
    return jobs


# UC-05.1 — steps 4-7
def start_job_analysis(user, profile, form) -> JobPost:
    """Save the posting a validated `JobAnalysisForm` holds and queue its analysis.

    The allowance is checked before the row is written: an analysis the plan
    does not allow must not leave a half-created job post behind. It is
    consumed only once the work is queued. Raises `Blocked` (quota exhausted or
    the AI switched off).

    The analysis runs in the profile's language, not the browser's: a posting
    analysed in a French workspace stays French even if the UI is being read in
    English.
    """
    blocked = quotas.blocked_message(user, UsageMetric.JOB_ANALYSIS)
    if blocked:
        raise Blocked(blocked)

    form.instance.profile = profile
    job = form.save()
    enqueue_job_analysis(job)
    quotas.consume(user, UsageMetric.JOB_ANALYSIS)
    return job


# UC-05.1 (step 8) and UC-05.5 (step 4) — what the job page shows: the section
# rail, the match tallies, the running tasks and the resume written for the job
def job_detail_context(job: JobPost) -> dict:
    by_key = {section.key: section for section in job.sections.all()}
    return {
        # Always the canonical order, including sections the posting had nothing
        # for — they show as empty rather than disappearing.
        "rail": [{"spec": spec, "section": by_key.get(spec.key)} for spec in SECTIONS],
        "match_summary": job.element_match_summary(),
        "tailored_resume": TailoredResume.objects.filter(job=job).first(),
        "ai_task": AITask.latest_for(job, AITask.JOB_ANALYSIS),
        "match_task": AITask.latest_for(job, AITask.JOB_MATCH),
    }


# UC-05 — a job post owns its sections and their rows, and the resume written
# for it goes with it; the confirmation page says so
def has_tailored_resume(job: JobPost) -> bool:
    return TailoredResume.objects.filter(job=job).exists()


# UC-05 — deleting a job post
def remove_job(job: JobPost) -> None:
    job.delete()


# ---------------------------------------------------------------------------
# UC-05.5 / UC-05.7 — Retrying, re-matching and re-analysing
# ---------------------------------------------------------------------------
# UC-05.7 — Alternative Scenario (Full Re-Analyze — Metered)
def reanalyze_job(user, job: JobPost) -> AITask:
    """Run the extraction again from the stored text.

    It is a second trip to the AI provider, so it costs the same as the first
    analysis and is metered the same way. Raises `Blocked`.
    """
    blocked = quotas.blocked_message(user, UsageMetric.JOB_ANALYSIS)
    if blocked:
        raise Blocked(blocked)
    task = enqueue_job_analysis(job)
    quotas.consume(user, UsageMetric.JOB_ANALYSIS)
    return task


# UC-05.7 — Main Success Scenario (Re-Match Against Profile — Free)
def rematch_job(job: JobPost) -> AITask:
    """Match every section of an already-extracted job against the profile again.

    Matching is part of the analysis the account was already charged for, so
    only the kill switch applies here, not the quota. Raises
    `PreconditionFailed` for a job that has not been extracted yet and `Blocked`
    when the AI is switched off.
    """
    if not job.sections.exists():
        raise PreconditionFailed(
            gettext("Analyze this job post first, then match it to your profile.")
        )
    unavailable = quotas.ai_unavailable_message()
    if unavailable:
        raise Blocked(unavailable)
    return enqueue_full_match(job)


# UC-05.5 — step 5: the per-tab Retry button
def rematch_section(section: JobSection) -> AITask:
    return enqueue_section_match(section)


# ---------------------------------------------------------------------------
# UC-05.6 — Real-Time Unified State Polling
# ---------------------------------------------------------------------------
def analysis_state(job: JobPost) -> dict:
    """Every section's state in one payload, so the rail updates without one
    request per section (spec §7.5). `is_running` is what stops the polling."""
    task = AITask.latest_for(job, AITask.JOB_ANALYSIS)
    match_task = AITask.latest_for(job, AITask.JOB_MATCH)
    live = [t for t in (task, match_task) if t and not t.is_terminal]
    sections = []
    for section in job.sections.all():
        summary = section.match_summary()
        sections.append(
            {
                "key": section.key,
                "id": section.pk,
                "state": section.match_state,
                "error": section.match_error,
                "total": summary["total"],
                "strong": summary["strong"],
                "partial": summary["partial"],
                "none": summary["none"],
                "analyzed": summary["analyzed"],
            }
        )
    return {
        "job_status": job.status,
        "sections": sections,
        "summary": job.element_match_summary(),
        "is_running": bool(live)
        or job.status in (JobPost.STATUS_PENDING, JobPost.STATUS_PROCESSING),
        "task_id": live[0].pk if live else None,
    }


# ---------------------------------------------------------------------------
# UC-06 — Interactive "Add to my profile"
# ---------------------------------------------------------------------------
# UC-06.1 — step 5, and its alternative flow for a section that has no
# counterpart on the profile
def add_target_for(element: JobElement) -> AddTarget:
    """Which profile object this requirement's section turns into. Raises
    `Refused` for a section that cannot be added to a profile."""
    target = get_add_target(element.section.key)
    if target is None:
        raise Refused(gettext("This section can't be added to your profile."))
    return target


# UC-06.1 — step 2: only rows of an addable section get the button
def can_add_to_profile(element: JobElement) -> bool:
    return get_add_target(element.section.key) is not None


# UC-06.1 — steps 5-6 and UC-06.2: the form a requirement opens, pre-filled from
# its text. With `data` it is the submitted form instead.
def add_to_profile_form(profile, element: JobElement, target: AddTarget, data=None):
    if data is None:
        return target.form_class(
            profile=profile, element=element, initial=target.initial_for(element)
        )
    return target.form_class(data, profile=profile, element=element)


# UC-06.3 — steps 2-4
def add_to_profile(element: JobElement, form) -> AITask:
    """Create the profile record a validated add-to-profile `form` describes, note
    on the requirement that it was answered, and queue a re-check of that one
    row."""
    form.save()
    element.added_to_profile_at = timezone.now()
    element.save(update_fields=["added_to_profile_at"])
    return rematch_element(element)


# UC-06.3 — step 4, and the re-evaluation that adds nothing
def rematch_element(element: JobElement) -> AITask:
    """Re-evaluate exactly one requirement against the profile as it is now.
    `element` comes back holding the state the task left it in (in development
    the task has already run)."""
    task = enqueue_element_match(element)
    element.refresh_from_db()
    return task


# UC-06.3 — steps 8-9: the counters to redraw once a re-evaluation has finished
def element_row_state(element: JobElement) -> dict:
    return {
        "section_summary": element.section.match_summary(),
        "summary": element.section.job.element_match_summary(),
    }
