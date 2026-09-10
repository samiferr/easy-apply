"""Background resume analysis and tailored-resume generation."""

import logging

from celery import shared_task
from django.utils.translation import gettext as _

from core.ai import AIServiceError
from core.models import AITask
from core.tasks import fail_task, get_task, guard, is_retryable

from .models import ResumeImport, TailoredResume

logger = logging.getLogger(__name__)
MAX_RETRIES = 3


@shared_task(bind=True, soft_time_limit=300)
@guard
def analyze_resume_import(self, resume_import_id: int, task_id: int) -> dict:
    """Extract text from the uploaded file, then parse it with the AI."""
    from .services.importer import run_analysis

    resume_import = ResumeImport.objects.filter(pk=resume_import_id).first()
    task = get_task(task_id)
    if resume_import is None:
        fail_task(task, _("That upload no longer exists."))
        return {"ok": False}

    if task:
        task.mark_running(_("Reading your resume"), steps_total=2)

    try:
        run_analysis(resume_import, progress=task)
    except AIServiceError as exc:
        if is_retryable(exc) and self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=5 * (2**self.request.retries))
        fail_task(task, str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("Unexpected error analyzing resume import %s", resume_import_id)
        fail_task(task, str(_("Something unexpected went wrong reading your resume.")))
        return {"ok": False}

    resume_import.refresh_from_db()
    if resume_import.status == ResumeImport.STATUS_FAILED:
        fail_task(task, resume_import.error_message or _("Couldn't read your resume."))
        return {"ok": False}

    if task:
        task.mark_done(_("Resume ready to review"))
    return {"ok": True}


def enqueue_resume_analysis(resume_import: ResumeImport) -> AITask:
    task = AITask.start_for(
        resume_import.user,
        AITask.RESUME_IMPORT,
        resume_import,
        steps_total=2,
        step=_("Queued"),
    )
    resume_import.status = ResumeImport.STATUS_PENDING
    resume_import.error_message = ""
    resume_import.save(update_fields=["status", "error_message"])
    async_result = analyze_resume_import.apply_async(args=(resume_import.pk, task.pk))
    task.celery_task_id = getattr(async_result, "id", "") or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    return task


@shared_task(bind=True, soft_time_limit=300)
@guard
def generate_tailored_resume_task(self, job_id: int, task_id: int) -> dict:
    from jobs.models import JobPost

    from .services.tailored import generate_tailored_resume

    job = JobPost.objects.filter(pk=job_id).select_related("user").first()
    task = get_task(task_id)
    if job is None:
        fail_task(task, _("That job post no longer exists."))
        return {"ok": False}

    if task:
        task.mark_running(_("Writing your tailored resume"))

    tailored = TailoredResume.objects.filter(job=job).first()
    if tailored:
        tailored.state = TailoredResume.STATE_PROCESSING
        tailored.error_message = ""
        tailored.save(update_fields=["state", "error_message"])

    try:
        generate_tailored_resume(job, job.user)
    except AIServiceError as exc:
        if is_retryable(exc) and self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=5 * (2**self.request.retries))
        TailoredResume.objects.filter(job=job).update(
            state=TailoredResume.STATE_FAILED, error_message=str(exc)
        )
        fail_task(task, str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("Unexpected error generating tailored resume for job %s", job_id)
        message = str(_("Something unexpected went wrong writing your resume."))
        TailoredResume.objects.filter(job=job).update(
            state=TailoredResume.STATE_FAILED, error_message=message
        )
        fail_task(task, message)
        return {"ok": False}

    if task:
        task.mark_done(_("Resume ready"))
    return {"ok": True}


def enqueue_tailored_resume(job, user) -> AITask:
    tailored, _created = TailoredResume.objects.get_or_create(
        job=job, defaults={"user": user}
    )
    tailored.state = TailoredResume.STATE_PENDING
    tailored.error_message = ""
    tailored.save(update_fields=["state", "error_message"])

    task = AITask.start_for(
        user, AITask.TAILORED_RESUME, tailored, steps_total=1, step=_("Queued")
    )
    async_result = generate_tailored_resume_task.apply_async(args=(job.pk, task.pk))
    task.celery_task_id = getattr(async_result, "id", "") or ""
    task.save(update_fields=["celery_task_id", "updated_at"])
    return task
