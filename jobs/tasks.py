"""Background job-analysis pipeline.

    chord(
        chain(fetch_job_text -> extract_job_sections),
        group(match_job_section for each matched section),
    ) -> finalize_job_analysis

A section that fails records its own failure and returns normally, so one bad
section never poisons the chord (spec §7.3).
"""

import logging

from celery import chain, chord, group, shared_task
from django.utils import timezone
from django.utils.translation import gettext as _

from core.ai import AIServiceError
from core.models import AITask
from core.tasks import fail_task, get_task, guard, is_retryable

from .models import JobElement, JobPost, JobSection
from .services.deepseek_client import analyze_job_text
from .services.fetcher import JobFetchError, fetch_job_post_text
from .services.importer import apply_analysis, matched_sections_for
from .services.matcher import (
    finalize_job_match,
    match_element_to_profile,
    match_section_to_profile,
)

logger = logging.getLogger(__name__)

RETRY_KWARGS = {"max_retries": 3, "countdown": 5}


# ---------------------------------------------------------------------------
# Step 1 — fetch
# ---------------------------------------------------------------------------
@shared_task(bind=True, soft_time_limit=120)
@guard
def fetch_job_text(self, job_id: int, task_id: int) -> dict:
    task = get_task(task_id)
    job = JobPost.objects.filter(pk=job_id).first()
    if job is None:
        return {"job_id": job_id, "task_id": task_id, "failed": True}

    if task:
        task.mark_running(_("Fetching the job posting"))
    job.status = JobPost.STATUS_PROCESSING
    job.error_message = ""
    job.save(update_fields=["status", "error_message"])

    try:
        if job.manual_text.strip():
            raw_text = job.manual_text.strip()
        else:
            raw_text = fetch_job_post_text(job.source_url)
    except JobFetchError as exc:
        job.status = JobPost.STATUS_FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        fail_task(task, str(exc))
        return {"job_id": job_id, "task_id": task_id, "failed": True}

    job.fetched_at = timezone.now()
    job.save(update_fields=["fetched_at"])
    if task:
        task.advance(_("Reading the posting"))
    return {"job_id": job_id, "task_id": task_id, "raw_text": raw_text, "failed": False}


# ---------------------------------------------------------------------------
# Step 2 — extract the 13 sections
# ---------------------------------------------------------------------------
@shared_task(bind=True, soft_time_limit=300)
@guard
def extract_job_sections(self, payload: dict, language: str = "en") -> dict:
    if payload.get("failed"):
        return payload

    job_id, task_id = payload["job_id"], payload["task_id"]
    task = get_task(task_id)
    job = JobPost.objects.filter(pk=job_id).first()
    if job is None:
        return {"job_id": job_id, "task_id": task_id, "failed": True}

    if task:
        task.set_step(_("Extracting the job's sections"))

    try:
        data = analyze_job_text(payload.get("raw_text", ""), job.source_url, language=language)
    except AIServiceError as exc:
        if is_retryable(exc) and self.request.retries < RETRY_KWARGS["max_retries"]:
            raise self.retry(exc=exc, countdown=5 * (2**self.request.retries))
        job.status = JobPost.STATUS_FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        fail_task(task, str(exc))
        return {"job_id": job_id, "task_id": task_id, "failed": True}
    except Exception:
        logger.exception("Unexpected error extracting job post %s", job_id)
        message = _("Something unexpected went wrong analyzing this job post.")
        job.status = JobPost.STATUS_FAILED
        job.error_message = message
        job.save(update_fields=["status", "error_message"])
        fail_task(task, message)
        return {"job_id": job_id, "task_id": task_id, "failed": True}

    apply_analysis(job, data, payload.get("raw_text", ""), language=language)

    sections = matched_sections_for(job)
    if task:
        # Now that we know how many sections carry rows, the total is exact.
        task.steps_total = 2 + len(sections)
        task.save(update_fields=["steps_total", "updated_at"])
        task.advance(_("Sections extracted"))

    return {
        "job_id": job_id,
        "task_id": task_id,
        "failed": False,
        "section_ids": [s.id for s in sections],
    }


# ---------------------------------------------------------------------------
# Step 3 — one task per matched section
# ---------------------------------------------------------------------------
@shared_task(bind=True, soft_time_limit=300)
@guard
def match_job_section(self, section_id: int, task_id: int | None = None) -> dict:
    """Match one section. Never raises out of the chord: a failure is recorded
    on the section and the user retries just that tab."""
    section = JobSection.objects.filter(pk=section_id).select_related("job").first()
    if section is None:
        return {"section_id": section_id, "ok": False}

    task = get_task(task_id) if task_id else None
    label = str(section.label)

    section.match_state = JobSection.RUNNING
    section.match_error = ""
    section.save(update_fields=["match_state", "match_error"])
    if task:
        task.set_step(_("Matching %(section)s") % {"section": label})

    try:
        result = match_section_to_profile(section)
    except AIServiceError as exc:
        if is_retryable(exc) and self.request.retries < RETRY_KWARGS["max_retries"]:
            raise self.retry(exc=exc, countdown=5 * (2**self.request.retries))
        section.match_state = JobSection.FAILED
        section.match_error = str(exc)
        section.save(update_fields=["match_state", "match_error"])
        if task:
            task.advance(_("%(section)s failed") % {"section": label})
        return {"section_id": section_id, "ok": False, "error": str(exc)}
    except Exception:
        logger.exception("Unexpected error matching section %s", section_id)
        section.match_state = JobSection.FAILED
        section.match_error = str(_("Something unexpected went wrong matching this section."))
        section.save(update_fields=["match_state", "match_error"])
        if task:
            task.advance(_("%(section)s failed") % {"section": label})
        return {"section_id": section_id, "ok": False}

    if task:
        task.advance(_("Matched %(section)s") % {"section": label})
    return {"section_id": section_id, "ok": True, **result}


# ---------------------------------------------------------------------------
# Step 4 — finalize
# ---------------------------------------------------------------------------
@shared_task(bind=True)
def finalize_job_analysis(self, results, job_id: int, task_id: int) -> dict:
    task = get_task(task_id)
    job = JobPost.objects.filter(pk=job_id).first()
    if job is None:
        return {"ok": False}

    finalize_job_match(job)
    failed = [r for r in (results or []) if isinstance(r, dict) and not r.get("ok")]
    if task:
        if failed and len(failed) == len(results or []):
            task.mark_failed(_("Every section failed to match. Please try again."))
        else:
            task.mark_done(_("Analysis complete"))
    return {"ok": True, "failed_sections": len(failed)}


# ---------------------------------------------------------------------------
# Public entry points — the only things views call
# ---------------------------------------------------------------------------
def enqueue_job_analysis(job: JobPost, language: str = "en") -> AITask:
    """Kick off the full pipeline: fetch -> extract -> match every section."""
    task = AITask.start_for(
        job.user,
        AITask.JOB_ANALYSIS,
        job,
        steps_total=2,
        step=_("Queued"),
    )
    job.status = JobPost.STATUS_PENDING
    job.error_message = ""
    job.save(update_fields=["status", "error_message"])

    workflow = chain(
        fetch_job_text.s(job.pk, task.pk),
        extract_job_sections.s(language),
        _dispatch_section_matches.s(),
    )
    async_result = workflow.apply_async()
    task.celery_task_id = getattr(async_result, "id", "") or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    return task


@shared_task(bind=True)
def _dispatch_section_matches(self, payload: dict):
    """Fan the extracted sections out into a chord.

    Split out of `extract_job_sections` so the section list is known before the
    group is built — a chord header cannot size its own body.
    """
    if payload.get("failed"):
        return payload

    job_id, task_id = payload["job_id"], payload["task_id"]
    section_ids = payload.get("section_ids") or []

    if not section_ids:
        return finalize_job_analysis.apply_async(args=([], job_id, task_id))

    return chord(
        group(match_job_section.s(sid, task_id) for sid in section_ids),
        finalize_job_analysis.s(job_id, task_id),
    ).apply_async()


def enqueue_section_match(section: JobSection) -> AITask:
    """Re-run matching for a single section (the per-tab Retry button)."""
    job = section.job
    task = AITask.start_for(
        job.user,
        AITask.JOB_MATCH,
        job,
        steps_total=1,
        step=_("Matching %(section)s") % {"section": str(section.label)},
    )
    async_result = match_job_section.apply_async(args=(section.pk, task.pk))
    task.celery_task_id = getattr(async_result, "id", "") or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    if task.state != AITask.FAILED:
        task.refresh_from_db()
        if not task.is_terminal:
            task.mark_done()
    return task


def enqueue_full_match(job: JobPost) -> AITask:
    """Re-match every section of an already-extracted job."""
    sections = matched_sections_for(job)
    task = AITask.start_for(
        job.user,
        AITask.JOB_MATCH,
        job,
        steps_total=max(1, len(sections)),
        step=_("Queued"),
    )
    if not sections:
        task.mark_done()
        return task

    async_result = chord(
        group(match_job_section.s(s.pk, task.pk) for s in sections),
        finalize_job_analysis.s(job.pk, task.pk),
    ).apply_async()
    task.celery_task_id = getattr(async_result, "id", "") or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    return task


@shared_task(bind=True, soft_time_limit=120)
@guard
def match_job_element(self, element_id: int, task_id: int) -> dict:
    """Re-evaluate exactly one element, after "Add to my profile"."""
    element = (
        JobElement.objects.filter(pk=element_id)
        .select_related("section", "section__job")
        .first()
    )
    task = get_task(task_id)
    if element is None:
        fail_task(task, _("That item no longer exists."))
        return {"ok": False}

    if task:
        task.mark_running(_("Re-evaluating this item"))

    try:
        match_element_to_profile(element)
    except AIServiceError as exc:
        if is_retryable(exc) and self.request.retries < RETRY_KWARGS["max_retries"]:
            raise self.retry(exc=exc, countdown=5 * (2**self.request.retries))
        JobElement.objects.filter(pk=element_id).update(is_evaluating=False)
        fail_task(task, str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("Unexpected error re-evaluating element %s", element_id)
        JobElement.objects.filter(pk=element_id).update(is_evaluating=False)
        fail_task(task, str(_("Something unexpected went wrong re-evaluating this item.")))
        return {"ok": False}

    if task:
        task.mark_done(_("Re-evaluated"))
    return {"ok": True}


def enqueue_element_match(element: JobElement) -> AITask:
    job = element.section.job
    task = AITask.start_for(
        job.user,
        AITask.JOB_MATCH,
        job,
        steps_total=1,
        step=_("Re-evaluating this item"),
    )
    JobElement.objects.filter(pk=element.pk).update(is_evaluating=True)
    async_result = match_job_element.apply_async(args=(element.pk, task.pk))
    task.celery_task_id = getattr(async_result, "id", "") or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    return task
