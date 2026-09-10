"""Prompts and AI calls for job analysis.

Three distinct calls live here, deliberately kept apart so each one carries the
smallest possible payload (see the refactor spec §6):

* `analyze_job_text`    — one extraction call producing all 13 fixed sections.
* `match_section`       — one section's elements against only its profile slice.
* `match_single_element` — one element, after "Add to my profile".

None of these may be called from a view: they run inside the Celery tasks in
jobs/tasks.py.
"""

import json

from core.ai import AIConfigError, AIServiceError, call_deepseek_json

from ..sections import SECTIONS, get_section

# Kept as aliases so existing imports keep working.
DeepSeekError = AIServiceError
DeepSeekConfigError = AIConfigError

_LANGUAGE_NAMES = {"en": "English", "fr": "French"}


def _language_clause(language_code: str) -> str:
    name = _LANGUAGE_NAMES.get((language_code or "en")[:2], "English")
    return (
        f"Write every piece of prose you produce — summaries, section bodies and "
        f"explanations — in {name}. Keep proper nouns (company names, product "
        f"names, technologies) in their original form."
    )


# --------------------------------------------------------------------------
# 1. Extraction
# --------------------------------------------------------------------------

_SECTION_SPEC_LINES = "\n".join(
    f'  - "{s.key}": {s.label}'
    + ("  [elements: atomic rows]" if s.has_elements else "  [body: prose]")
    for s in SECTIONS
)

EXTRACTION_SYSTEM_PROMPT = f"""You are an expert job-post analyst. You read a raw \
job posting and break it into a FIXED set of sections, the way a careful \
candidate would triage it before deciding whether to apply.

The section list is CLOSED. You must use exactly these keys and no others. \
Never invent a section, never rename one, never merge two:

{_SECTION_SPEC_LINES}

Sections marked [body: prose] carry a "body" string and an empty "elements" \
list. Sections marked [elements: atomic rows] carry a list of short, atomic \
strings in "elements" and an empty "body".

Return ONLY a single JSON object (no markdown fences, no commentary) with \
exactly this shape:

{{
  "title": string,
  "seniority_level": string,
  "summary": string,
  "location": string,
  "work_arrangement": "remote" | "hybrid" | "onsite" | "unclear",
  "timezone_expectations": string,
  "relocation_offered": true | false | null,
  "travel_percentage": string,
  "salary_min": number | null,
  "salary_max": number | null,
  "salary_currency": string,
  "salary_period": string,
  "compensation_notes": string,
  "benefits": [string],
  "company_name": string,
  "company_size": string,
  "company_stage": string,
  "company_industry": string,
  "company_mission": string,
  "reports_to": string,
  "application_instructions": string,
  "application_deadline": string,
  "red_flags": [string],
  "growth_language_notes": string,
  "diversity_statement": string,
  "sections": [
    {{"key": <one of the keys above>, "body": string, "elements": [string]}}
  ]
}}

Rules:
- Only extract what the text actually states. Use "" (empty string), null, or \
an empty list for anything not mentioned — never invent facts.
- Split every responsibility/requirement/benefit into individual, atomic \
statements (one clear idea per array item), even if the source combined \
several into one bullet.
- "location_arrangement" elements are the individual facts a candidate would \
check against their preferences, e.g. "Hybrid — 3 days on-site in Montreal", \
"Up to 20% travel", "Must overlap EST until 1pm".
- "compensation_benefits" elements are the salary line and each benefit as its \
own row, e.g. "120,000-140,000 CAD per year", "Health insurance", \
"Dental care", "4 weeks paid vacation".
- "required_technical_skills" is for true dealbreakers; \
"desirable_technical_skills" for nice-to-haves. If the posting does not \
distinguish them, put everything in required and leave desirable empty.
- "languages" elements are spoken/written language requirements only \
(e.g. "French - professional working proficiency"), never programming languages.
- "education_certifications" elements are degree and certification \
requirements, one per row.
- Omit a section entirely if the posting says nothing about it — do not emit \
an entry with an empty body and no elements.
- salary_min/salary_max are plain numbers in the stated currency's base unit \
(no symbols, no commas), or null if no range is given.
"""


def analyze_job_text(raw_text: str, source_url: str = "", language: str = "en") -> dict:
    truncated = raw_text[:18000]
    user_content = (
        f"Job posting URL: {source_url or '(pasted manually)'}\n\n"
        f"{_language_clause(language)}\n\n"
        f"--- Job posting text ---\n{truncated}"
    )
    return call_deepseek_json(EXTRACTION_SYSTEM_PROMPT, user_content)


# --------------------------------------------------------------------------
# 2. Matching — one section at a time, with only that section's profile slice
# --------------------------------------------------------------------------

MATCH_SYSTEM_PROMPT = """You are an expert technical recruiter helping a \
candidate see how well their profile matches ONE section of a specific job \
posting.

You are given a JSON object with: "section" (the section's label), "elements" \
(a list of {"id": integer, "text": string} — every row in that section) and \
"candidate_profile" (ONLY the part of the candidate's profile that is relevant \
to this section — do not ask for or assume anything else).

Evaluate EVERY element independently, one by one — go through the list in \
order, do not let your judgment of one element influence another, and do not \
skip any. For each, decide whether the candidate's profile provides evidence \
that satisfies it:

- "strong": the profile clearly and directly demonstrates or satisfies this.
- "partial": there is related or adjacent evidence that does not fully cover it \
(fewer years than asked, an adjacent technology, a preference that only \
partly overlaps).
- "none": nothing in the profile addresses this.

Return ONLY a single JSON object (no markdown fences, no commentary):

{
  "matches": [
    {"element_id": integer, "status": "strong" | "partial" | "none", "evidence": string}
  ]
}

Rules:
- Include exactly one entry per element id you were given.
- "evidence" is a short, one-sentence explanation naming the SPECIFIC skill, \
role, degree, language, certificate or stated preference from the candidate's \
profile that supports your verdict. If status is "none", briefly say what is \
missing instead.
- Never invent profile facts that were not given to you. The profile slice you \
receive is complete for this section — if something is not in it, the \
candidate does not have it.
"""


def _match_payload(section_key: str, elements, profile_slice: dict) -> str:
    section = get_section(section_key)
    return json.dumps(
        {
            "section": str(section.label) if section else section_key,
            "elements": [{"id": e.id, "text": e.text} for e in elements],
            "candidate_profile": profile_slice,
        },
        ensure_ascii=False,
    )


def match_section(section_key: str, elements, profile_slice: dict, language: str = "en") -> dict:
    """Evaluate every element of one section against only its profile slice."""
    user_content = f"{_language_clause(language)}\n\n{_match_payload(section_key, elements, profile_slice)}"
    return call_deepseek_json(MATCH_SYSTEM_PROMPT, user_content, temperature=0.1)


def match_single_element(section_key: str, element, profile_slice: dict, language: str = "en") -> dict:
    """Re-evaluate exactly one element — used after "Add to my profile"."""
    user_content = f"{_language_clause(language)}\n\n{_match_payload(section_key, [element], profile_slice)}"
    return call_deepseek_json(MATCH_SYSTEM_PROMPT, user_content, temperature=0.1)
