"""Matches a job's extracted requirements against a candidate's profile,
one requirement at a time, via the shared DeepSeek client.
"""

import json
import logging

from django.db import transaction
from django.utils import timezone

from core.ai import AIServiceError, call_deepseek_json
from core.utils import build_profile_snapshot, profile_snapshot_is_empty

from ..models import Requirement

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert technical recruiter helping a candidate \
see how well their profile matches a specific job's requirements. You will \
be given a JSON object with two keys: "requirements" (a list of \
{"id": integer, "category": string, "text": string} — every requirement or \
responsibility line extracted from the job posting) and "candidate_profile" \
(the candidate's soft/technical skills, languages, work experience with \
highlights, degrees and certificates).

Evaluate EVERY requirement independently, one by one — go through the list \
in order, do not let your judgment of one requirement influence another, \
and do not skip any. For each, decide whether the candidate's profile \
provides evidence that satisfies it:

- "strong": the profile clearly and directly demonstrates this (an explicit \
matching skill, a role/degree/certificate that squarely covers it, or \
enough years of directly relevant experience).
- "partial": there's related or adjacent evidence, but it doesn't fully \
cover the requirement (e.g. fewer years than asked, an adjacent \
technology, or an implied-but-not-stated skill).
- "none": nothing in the profile addresses this requirement.

Return ONLY a single JSON object (no markdown fences, no commentary) with \
this shape:

{
  "matches": [
    {"requirement_id": integer, "status": "strong" | "partial" | "none", "evidence": string}
  ]
}

Rules:
- Include exactly one entry per requirement id you were given.
- "evidence" is a short, one-sentence explanation naming the SPECIFIC \
skill, role, degree or certificate from the candidate's profile that \
supports your verdict (e.g. "5 years as Backend Engineer at Acme Corp \
using Python, listed as an Expert-level skill"). If status is "none", \
briefly say what's missing instead (e.g. "No Kubernetes experience or \
certification listed").
- Never invent profile facts that weren't given to you.
"""


def match_requirements_to_profile(job, user) -> dict:
    """Evaluate every requirement on `job` against `user`'s profile and
    write the verdicts onto each Requirement. Returns a summary dict —
    either {"skipped": "no_requirements" | "empty_profile"} or
    {"matched": n, "total": n}. Raises AIServiceError on failure."""

    requirements = list(
        Requirement.objects.filter(category__job=job).select_related("category")
    )
    if not requirements:
        return {"skipped": "no_requirements"}

    profile_snapshot = build_profile_snapshot(user)
    if profile_snapshot_is_empty(profile_snapshot):
        return {"skipped": "empty_profile"}

    requirements_payload = [
        {"id": r.id, "category": r.category.name, "text": r.text} for r in requirements
    ]
    user_content = json.dumps(
        {"requirements": requirements_payload, "candidate_profile": profile_snapshot}
    )
    data = call_deepseek_json(SYSTEM_PROMPT, user_content, temperature=0.1)

    matches = data.get("matches")
    if not isinstance(matches, list):
        raise AIServiceError("The AI matching service returned an unexpected response.")

    by_id = {r.id: r for r in requirements}
    valid_statuses = {choice[0] for choice in Requirement.MATCH_CHOICES}
    updated = []
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        try:
            req_id = int(entry.get("requirement_id"))
        except (TypeError, ValueError):
            continue
        requirement = by_id.get(req_id)
        if requirement is None:
            continue

        status = entry.get("status")
        if status not in valid_statuses:
            status = Requirement.NONE
        evidence = entry.get("evidence")
        evidence = evidence.strip()[:500] if isinstance(evidence, str) else ""

        requirement.match_status = status
        requirement.match_evidence = evidence
        updated.append(requirement)

    with transaction.atomic():
        if updated:
            Requirement.objects.bulk_update(updated, ["match_status", "match_evidence"])
        job.profile_matched_at = timezone.now()
        job.save(update_fields=["profile_matched_at"])

    return {"matched": len(updated), "total": len(requirements)}
