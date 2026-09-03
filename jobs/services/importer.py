"""Turns the AI's JSON response into JobPost / RequirementCategory /
Requirement rows, defensively — the AI is asked for a specific shape but
we never trust it blindly.
"""

import logging

from django.db import transaction
from django.utils import timezone

from ..models import JobPost, Requirement, RequirementCategory
from .deepseek_client import DeepSeekError, analyze_job_text
from .fetcher import JobFetchError, fetch_job_post_text

logger = logging.getLogger(__name__)

CATEGORY_TYPES = {choice[0] for choice in RequirementCategory.TYPE_CHOICES}
WORK_ARRANGEMENTS = {choice[0] for choice in JobPost.WORK_ARRANGEMENT_CHOICES}


def _clean_str(value, max_length=None):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value[:max_length] if max_length else value


def _clean_int(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _clean_bool(value):
    return value if isinstance(value, bool) else None


def _clean_list(value):
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def apply_analysis(job: JobPost, data: dict, raw_text: str) -> None:
    """Populate `job` (and its categories/requirements) from the AI's dict.

    Replaces any previously-imported categories, so this doubles as the
    re-analysis path.
    """
    with transaction.atomic():
        job.title = _clean_str(data.get("title"), 200)
        job.seniority_level = _clean_str(data.get("seniority_level"), 100)
        job.summary = _clean_str(data.get("summary"))

        job.location = _clean_str(data.get("location"), 200)
        work_arrangement = _clean_str(data.get("work_arrangement")).lower()
        job.work_arrangement = work_arrangement if work_arrangement in WORK_ARRANGEMENTS else ""
        job.timezone_expectations = _clean_str(data.get("timezone_expectations"), 200)
        job.relocation_offered = _clean_bool(data.get("relocation_offered"))
        job.travel_percentage = _clean_str(data.get("travel_percentage"), 100)

        job.salary_min = _clean_int(data.get("salary_min"))
        job.salary_max = _clean_int(data.get("salary_max"))
        job.salary_currency = _clean_str(data.get("salary_currency"), 10)
        job.salary_period = _clean_str(data.get("salary_period"), 20)
        job.compensation_notes = _clean_str(data.get("compensation_notes"))
        job.benefits = "\n".join(_clean_list(data.get("benefits")))

        job.company_name = _clean_str(data.get("company_name"), 200)
        job.company_size = _clean_str(data.get("company_size"), 100)
        job.company_stage = _clean_str(data.get("company_stage"), 100)
        job.company_industry = _clean_str(data.get("company_industry"), 150)
        job.company_mission = _clean_str(data.get("company_mission"))
        job.reports_to = _clean_str(data.get("reports_to"), 150)

        job.application_instructions = _clean_str(data.get("application_instructions"))
        job.application_deadline = _clean_str(data.get("application_deadline"), 100)

        job.red_flags = "\n".join(_clean_list(data.get("red_flags")))
        job.growth_language_notes = _clean_str(data.get("growth_language_notes"))
        job.diversity_statement = _clean_str(data.get("diversity_statement"))

        job.raw_text = raw_text
        job.ai_model = _clean_str(data.get("_model"), 100)
        job.analyzed_at = timezone.now()
        job.status = JobPost.STATUS_COMPLETED
        job.error_message = ""
        job.save()

        job.categories.all().delete()
        categories = data.get("categories")
        if isinstance(categories, list):
            order = 0
            for entry in categories:
                if not isinstance(entry, dict):
                    continue
                requirements = _clean_list(entry.get("requirements"))
                if not requirements:
                    continue
                name = _clean_str(entry.get("name"), 150) or "Other"
                category_type = _clean_str(entry.get("type")).lower()
                if category_type not in CATEGORY_TYPES:
                    category_type = RequirementCategory.OTHER
                category = RequirementCategory.objects.create(
                    job=job, name=name, category_type=category_type, order=order
                )
                order += 1
                Requirement.objects.bulk_create(
                    Requirement(category=category, text=text, order=r_order)
                    for r_order, text in enumerate(requirements)
                )


def run_analysis(job: JobPost) -> None:
    """Fetch/accept text, call the AI, and populate `job`.

    Always leaves `job` saved with a final status (completed or failed) —
    never raises, so callers can safely redirect to the detail page either way.
    """
    job.status = JobPost.STATUS_PROCESSING
    job.save(update_fields=["status"])

    try:
        if job.manual_text.strip():
            raw_text = job.manual_text.strip()
        else:
            raw_text = fetch_job_post_text(job.source_url)
        job.fetched_at = timezone.now()
        data = analyze_job_text(raw_text, job.source_url)
        apply_analysis(job, data, raw_text)
    except (JobFetchError, DeepSeekError) as exc:
        job.status = JobPost.STATUS_FAILED
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message", "fetched_at"])
    except Exception:
        logger.exception("Unexpected error analyzing job post %s", job.pk)
        job.status = JobPost.STATUS_FAILED
        job.error_message = "Something unexpected went wrong analyzing this job post."
        job.save(update_fields=["status", "error_message", "fetched_at"])
