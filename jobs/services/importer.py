"""Turns the AI's JSON response into JobPost / JobSection / JobElement rows,
defensively — the AI is asked for a specific shape but we never trust it.

Note the transaction discipline: `apply_analysis` does database work only. The
AI call happens before it, in jobs/tasks.py, so a write lock is never held
across a 30-second HTTP request (the SQLite worker concern in spec §7.1).
"""

import logging

from django.db import transaction
from django.utils import timezone

from ..models import JobElement, JobPost, JobSection
from ..sections import ELEMENT_SECTION_KEYS, SECTION_MAP, is_valid_key, order_for

logger = logging.getLogger(__name__)

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


def normalize_sections(data: dict) -> list[dict]:
    """Validate the AI's `sections` against the closed enum.

    Anything the AI invents is discarded; anything it duplicates is merged into
    the first occurrence. Returns entries in the canonical rail order.
    """
    raw = data.get("sections")
    if not isinstance(raw, list):
        return []

    by_key: dict[str, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = _clean_str(entry.get("key")).lower()
        if not is_valid_key(key):
            logger.info("Discarding unknown job section key from AI response: %r", key)
            continue

        body = _clean_str(entry.get("body"))
        elements = _clean_list(entry.get("elements"))
        # A prose section never carries rows, and a row section never carries prose.
        if key in ELEMENT_SECTION_KEYS:
            body = ""
        else:
            elements = []

        if key in by_key:
            by_key[key]["body"] = by_key[key]["body"] or body
            by_key[key]["elements"].extend(
                e for e in elements if e not in by_key[key]["elements"]
            )
        else:
            by_key[key] = {"key": key, "body": body, "elements": elements}

    # Drop entries with nothing in them at all.
    populated = [e for e in by_key.values() if e["body"] or e["elements"]]
    populated.sort(key=lambda e: order_for(e["key"]))
    return populated


def _fallback_sections(job: JobPost) -> list[dict]:
    """Derive prose/rows from the scalar JobPost fields.

    Used to fill sections the AI left out even though the scalar extraction
    picked something up, so the rail is never emptier than the data.
    """
    out: dict[str, dict] = {}

    def put(key, body="", elements=()):
        elements = [e for e in elements if e]
        if body or elements:
            out[key] = {"key": key, "body": body, "elements": list(elements)}

    put("overview", body=job.summary)
    company_bits = [
        b for b in [
            job.company_name, job.company_industry, job.company_stage,
            job.company_size, job.company_mission,
        ] if b
    ]
    put("company", body="\n".join(company_bits))
    put(
        "location_arrangement",
        elements=[
            job.location,
            job.get_work_arrangement_display() if job.work_arrangement else "",
            job.timezone_expectations,
            job.travel_percentage,
        ],
    )
    put(
        "compensation_benefits",
        elements=[job.salary_range_display, *job.benefits_list],
    )
    put("how_to_apply", body=job.application_instructions)
    put(
        "worth_noting",
        body="\n".join(b for b in [job.growth_language_notes, job.diversity_statement] if b),
    )
    put("red_flags", elements=[]) if not job.red_flags_list else put(
        "red_flags", body="\n".join(job.red_flags_list)
    )
    return list(out.values())


def apply_analysis(job: JobPost, data: dict, raw_text: str, language: str = "en") -> None:
    """Populate `job` and its sections/elements from the AI's dict.

    Pure database work — no network calls — so the transaction below is short.
    Replaces any previously-imported sections, so this doubles as re-analysis.
    """
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
    job.analysis_language = (language or "en")[:10]
    job.analyzed_at = timezone.now()
    job.profile_matched_at = None
    job.status = JobPost.STATUS_COMPLETED
    job.error_message = ""

    sections = normalize_sections(data)
    seen = {entry["key"] for entry in sections}
    # Fill any section the AI skipped but the scalar fields cover.
    sections.extend(e for e in _fallback_sections(job) if e["key"] not in seen)
    sections.sort(key=lambda e: order_for(e["key"]))

    with transaction.atomic():
        job.save()
        job.sections.all().delete()
        for entry in sections:
            section = JobSection.objects.create(
                job=job,
                key=entry["key"],
                order=order_for(entry["key"]),
                body=entry["body"],
                match_state=JobSection.IDLE,
            )
            if entry["elements"]:
                JobElement.objects.bulk_create(
                    JobElement(section=section, text=text, order=i)
                    for i, text in enumerate(entry["elements"])
                )


def matched_sections_for(job: JobPost):
    """The sections of `job` that carry rows and are compared to the profile."""
    return [
        s
        for s in job.sections.filter(key__in=SECTION_MAP.keys()).prefetch_related("elements")
        if s.is_matched_section and s.elements.exists()
    ]
