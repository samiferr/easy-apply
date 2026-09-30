"""Turns raw resume text into structured data covering profile info,
soft/technical skills, languages, work experience, degrees and
certificates, via the shared DeepSeek client. The prompts are loaded from
`prompts/resume/`.

Use case: UC-04.2 (step 5) in docs/use-cases/UC04_RESUME_PARSING_ONBOARDING.md.
"""

from core.ai import call_deepseek_json
from core.language import language_clause
from core.parallel import run_parallel
from core.prompts import load_prompt

#: One extraction per section, each with its own prompt file and the keys it
#: returns. Sections are independent, so they are asked for at the same time.
PARSE_SECTIONS = {
    "profile": ("profile",),
    "skills": ("soft_skills", "technical_skills"),
    "languages": ("languages",),
    "experience": ("experience",),
    "degrees": ("degrees",),
    "certificates": ("certificates",),
}

_SHARED = load_prompt("resume/parse/shared").rstrip("\n")
SECTION_PROMPTS = {
    name: f"{_SHARED}\n\n{load_prompt(f'resume/parse/{name}')}" for name in PARSE_SECTIONS
}
#: Every section prompt, for code that checks them as a whole.
SYSTEM_PROMPT = "\n\n".join(SECTION_PROMPTS.values())


# UC-04.2 — Background Asynchronous Extraction via DeepSeek LLM (steps 5-6)
def analyze_resume_text(
    raw_text: str,
    soft_categories: list,
    technical_categories: list,
    language: str = "en",
) -> dict:
    """Parse a resume into structured data, written in `language`.

    One AI call per section runs concurrently (see `PARSE_SECTIONS`), each
    returning only its own keys; the answers are merged into one dict. A failure
    in some sections keeps the others (`_failed_sections` names the ones lost);
    only when every section fails is the error raised.

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

    def ask(name):
        note = f"{categories_note}\n\n" if name == "skills" else ""
        user_content = (
            f"{language_clause(language)}\n\n{note}--- Resume text ---\n{truncated}"
        )
        return lambda: call_deepseek_json(SECTION_PROMPTS[name], user_content)

    answers, errors = run_parallel(
        {name: ask(name) for name in PARSE_SECTIONS}, keep_partial=True
    )

    merged = {}
    for name, keys in PARSE_SECTIONS.items():
        if name not in answers:
            continue
        for key in keys:
            if key in answers[name]:
                merged[key] = answers[name][key]
        if "_model" in answers[name]:
            merged.setdefault("_model", answers[name]["_model"])
    if errors:
        merged["_failed_sections"] = list(errors)
    return merged
