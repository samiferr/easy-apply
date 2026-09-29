"""AI calls for job analysis.

Three distinct calls live here, deliberately kept apart so each one carries the
smallest possible payload (see the refactor spec §6). Their prompts are not in
this file: they are loaded from `prompts/jobs/` (see `prompts/README.md`).

* `analyze_job_text`    — one extraction call producing all 13 fixed sections.
* `match_section`       — one section's elements against only its profile slice.
* `match_single_element` — one element, after "Add to my profile".

None of these may be called from a view: they run inside the Celery tasks in
jobs/tasks.py.
"""

import json

from core.ai import AIConfigError, AIServiceError, call_deepseek_json
from core.language import language_clause, use_language
from core.prompts import load_prompt

from ..sections import SECTIONS, get_section

# Kept as aliases so existing imports keep working.
DeepSeekError = AIServiceError
DeepSeekConfigError = AIConfigError


# --------------------------------------------------------------------------
# 1. Extraction
# --------------------------------------------------------------------------

_SECTION_SPEC_LINES = "\n".join(
    f'  - "{s.key}": {s.label}'
    + ("  [elements: atomic rows]" if s.has_elements else "  [body: prose]")
    for s in SECTIONS
)

EXTRACTION_SYSTEM_PROMPT = load_prompt("jobs/extract_sections", section_spec=_SECTION_SPEC_LINES)


def analyze_job_text(raw_text: str, language: str = "en") -> dict:
    truncated = raw_text[:18000]
    user_content = (
        f"{language_clause(language)}\n\n"
        f"--- Job posting text ---\n{truncated}"
    )
    return call_deepseek_json(EXTRACTION_SYSTEM_PROMPT, user_content)


# --------------------------------------------------------------------------
# 2. Matching — one section at a time, with only that section's profile slice
# --------------------------------------------------------------------------

MATCH_SYSTEM_PROMPT = load_prompt("jobs/match_section")


def _match_payload(section_key: str, elements, profile_slice: dict, language: str) -> str:
    """The JSON the matcher sends. The section label is resolved under the
    profile's language so the model is not handed an English label and then
    asked to answer in French."""
    section = get_section(section_key)
    with use_language(language):
        label = str(section.label) if section else section_key
    return json.dumps(
        {
            "section": label,
            "elements": [{"id": e.id, "text": e.text} for e in elements],
            "candidate_profile": profile_slice,
        },
        ensure_ascii=False,
    )


def match_section(section_key: str, elements, profile_slice: dict, language: str = "en") -> dict:
    """Evaluate every element of one section against only its profile slice."""
    payload = _match_payload(section_key, elements, profile_slice, language)
    user_content = f"{language_clause(language)}\n\n{payload}"
    return call_deepseek_json(MATCH_SYSTEM_PROMPT, user_content, temperature=0.1)


def match_single_element(section_key: str, element, profile_slice: dict, language: str = "en") -> dict:
    """Re-evaluate exactly one element — used after "Add to my profile"."""
    payload = _match_payload(section_key, [element], profile_slice, language)
    user_content = f"{language_clause(language)}\n\n{payload}"
    return call_deepseek_json(MATCH_SYSTEM_PROMPT, user_content, temperature=0.1)
