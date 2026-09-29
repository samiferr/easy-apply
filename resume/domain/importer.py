"""Orchestrates resume analysis: extract the text, ask the AI, store the result.

Everything is written into the profile the upload belongs to, so importing a
resume into one workspace never touches another. What the candidate does with
the result — the review checklist and the selective import — is in
resume/services.py. The readers at the top are shared with it: the AI's JSON is
never trusted to have the types it was asked for.

Use case: UC-04.2 in docs/use-cases/UC04_RESUME_PARSING_ONBOARDING.md.
"""

import logging
from datetime import datetime

from django.utils import timezone

from core.ai import AIServiceError
from skills.models import SkillCategory

from .deepseek_resume import analyze_resume_text
from .extractor import ResumeExtractError, extract_resume_text

logger = logging.getLogger(__name__)


def clean_str(value, max_length=None):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value[:max_length] if max_length else value


def clean_list_of_dicts(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def clean_str_list(value):
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


# --- Pipeline: extract text, call the AI, store the result ------------------

# UC-04.2 — Background Asynchronous Extraction via DeepSeek LLM (steps 3-7)
def run_analysis(resume_import, progress=None) -> None:
    """Extract text from the uploaded file, call the AI, and store the
    result on `resume_import`. Always leaves it saved with a final status
    (completed or failed) — never raises.

    `progress` is the AITask driving this run, if any: step 1 is text
    extraction, step 2 is the AI parse.
    """
    resume_import.status = resume_import.STATUS_PROCESSING
    resume_import.save(update_fields=["status"])

    try:
        raw_text = extract_resume_text(resume_import.file)
        resume_import.raw_text = raw_text
        if progress is not None:
            progress.advance("Understanding your resume")

        soft_categories = list(
            SkillCategory.objects.filter(kind=SkillCategory.SOFT).values_list("name", flat=True)
        )
        technical_categories = list(
            SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).values_list(
                "name", flat=True
            )
        )
        # The AI call sits outside any transaction — see spec §7.1. The
        # upload belongs to a profile, and that profile's language is what the
        # parsed prose comes back in.
        data = analyze_resume_text(
            raw_text,
            soft_categories,
            technical_categories,
            language=resume_import.profile.language,
        )

        resume_import.ai_response = data
        resume_import.ai_model = clean_str(data.get("_model"), 100)
        resume_import.status = resume_import.STATUS_COMPLETED
        resume_import.analyzed_at = timezone.now()
        resume_import.error_message = ""
        resume_import.save(
            update_fields=[
                "raw_text", "ai_response", "ai_model", "status", "analyzed_at", "error_message",
            ]
        )
    except (ResumeExtractError, AIServiceError) as exc:
        resume_import.status = resume_import.STATUS_FAILED
        resume_import.error_message = str(exc)
        resume_import.save(update_fields=["status", "error_message", "raw_text"])
    except Exception:
        logger.exception("Unexpected error analyzing resume %s", resume_import.pk)
        resume_import.status = resume_import.STATUS_FAILED
        resume_import.error_message = "Something unexpected went wrong analyzing this resume."
        resume_import.save(update_fields=["status", "error_message"])
