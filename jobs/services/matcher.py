"""Matches a job's sections against the candidate's profile.

Two entry points, both called from Celery tasks (never from a view):

* `match_section_to_profile(section)` — one section, one AI call, carrying only
  that section's profile slice.
* `match_element_to_profile(element)` — one row, after "Add to my profile".

Both short-circuit without any HTTP call when the mapped profile slice is
empty, and both keep the AI call outside the write transaction.
"""

import logging

from django.db import transaction
from django.utils import timezone

from core.ai import AIServiceError
from core.utils import build_profile_slice, empty_slice_hint, profile_slice_is_empty

from ..models import JobElement, JobSection
from .deepseek_client import match_section, match_single_element

logger = logging.getLogger(__name__)

VALID_STATUSES = {choice[0] for choice in JobElement.MATCH_CHOICES}


def _parse_matches(data: dict, by_id: dict[int, JobElement]) -> list[JobElement]:
    """Read the AI's verdicts onto the in-memory elements. Never trusted:
    unknown ids are dropped and unknown statuses fall back to "none"."""
    matches = data.get("matches")
    if not isinstance(matches, list):
        raise AIServiceError("The AI matching service returned an unexpected response.")

    now = timezone.now()
    updated: list[JobElement] = []
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        try:
            element_id = int(entry.get("element_id"))
        except (TypeError, ValueError):
            continue
        element = by_id.get(element_id)
        if element is None:
            continue

        status = entry.get("status")
        if status not in VALID_STATUSES:
            status = JobElement.NONE
        evidence = entry.get("evidence")
        evidence = evidence.strip()[:500] if isinstance(evidence, str) else ""

        element.match_status = status
        element.match_evidence = evidence
        element.evaluated_at = now
        element.is_evaluating = False
        updated.append(element)
    return updated


def _apply_empty_slice(elements, section_key: str) -> list[JobElement]:
    """Mark every element "not covered" without calling the AI."""
    hint = empty_slice_hint(section_key)
    now = timezone.now()
    for element in elements:
        element.match_status = JobElement.NONE
        element.match_evidence = hint
        element.evaluated_at = now
        element.is_evaluating = False
    return list(elements)


def _save(elements: list[JobElement]):
    if elements:
        JobElement.objects.bulk_update(
            elements,
            ["match_status", "match_evidence", "evaluated_at", "is_evaluating"],
        )


def match_section_to_profile(section: JobSection, user=None) -> dict:
    """Evaluate every element of one section. Returns a small summary dict.

    Raises AIServiceError on failure; the caller (the Celery task) records that
    on the section and on the AITask.
    """
    user = user or section.job.user
    elements = list(section.elements.all())
    if not elements:
        return {"skipped": "no_elements", "matched": 0, "total": 0}
    if not section.is_matched_section:
        return {"skipped": "not_matched_section", "matched": 0, "total": len(elements)}

    profile_slice = build_profile_slice(user, section.key)

    # Spec §6.2 — an empty slice never costs an API call.
    if profile_slice_is_empty(profile_slice):
        updated = _apply_empty_slice(elements, section.key)
        with transaction.atomic():
            _save(updated)
            section.match_state = JobSection.DONE
            section.match_error = ""
            section.matched_at = timezone.now()
            section.save(update_fields=["match_state", "match_error", "matched_at"])
        return {"skipped": "empty_slice", "matched": len(updated), "total": len(elements)}

    # The AI call happens here, outside any transaction.
    data = match_section(
        section.key, elements, profile_slice, language=section.job.analysis_language or "en"
    )
    updated = _parse_matches(data, {e.id: e for e in elements})

    with transaction.atomic():
        _save(updated)
        section.match_state = JobSection.DONE
        section.match_error = ""
        section.matched_at = timezone.now()
        section.save(update_fields=["match_state", "match_error", "matched_at"])

    return {"matched": len(updated), "total": len(elements)}


def match_element_to_profile(element: JobElement, user=None) -> dict:
    """Re-evaluate exactly one element — nothing else on the job is touched."""
    section = element.section
    user = user or section.job.user

    if not section.is_matched_section:
        return {"skipped": "not_matched_section"}

    profile_slice = build_profile_slice(user, section.key)

    if profile_slice_is_empty(profile_slice):
        updated = _apply_empty_slice([element], section.key)
        _save(updated)
        return {"skipped": "empty_slice", "matched": 1}

    data = match_single_element(
        section.key, element, profile_slice, language=section.job.analysis_language or "en"
    )
    updated = _parse_matches(data, {element.id: element})
    if not updated:
        raise AIServiceError("The AI matching service didn't return a verdict for this item.")
    _save(updated)
    return {"matched": 1}


def finalize_job_match(job) -> dict:
    """Stamp the job once every section has been through the matcher."""
    job.profile_matched_at = timezone.now()
    job.save(update_fields=["profile_matched_at"])
    return job.element_match_summary()
