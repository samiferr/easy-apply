"""Turns raw resume text into structured data covering profile info,
soft/technical skills, languages, work experience, degrees and
certificates, via the shared DeepSeek client. The prompts are loaded from
`prompts/resume/`.

Use case: UC-04.2 (step 5) in docs/use-cases/UC04_RESUME_PARSING_ONBOARDING.md.
"""

from core.ai import call_deepseek_json
from core.language import language_clause
from core.prompts import load_prompt

SYSTEM_PROMPT = load_prompt("resume/parse_resume")


# UC-04.2 — Background Asynchronous Extraction via DeepSeek LLM (steps 5-6)
def analyze_resume_text(
    raw_text: str,
    soft_categories: list,
    technical_categories: list,
    language: str = "en",
) -> dict:
    """Parse a resume into structured data, written in `language`.

    The resume itself may be in any language: the prose the model produces from
    it (headline, bio, highlight bullets, category names) is normalized into the
    profile's language, so a French profile never ends up half English.
    """
    truncated = raw_text[:20000]
    categories_note = load_prompt(
        "resume/skill_categories_note",
        soft_categories=", ".join(soft_categories) or "(none yet)",
        technical_categories=", ".join(technical_categories) or "(none yet)",
    ).strip()
    user_content = (
        f"{language_clause(language)}\n\n{categories_note}\n\n"
        f"--- Resume text ---\n{truncated}"
    )
    return call_deepseek_json(SYSTEM_PROMPT, user_content)
