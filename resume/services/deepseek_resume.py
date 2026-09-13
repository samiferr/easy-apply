"""Turns raw resume text into structured data covering profile info,
soft/technical skills, languages, work experience, degrees and
certificates, via the shared DeepSeek client.
"""

from core.ai import call_deepseek_json
from core.language import language_clause

SYSTEM_PROMPT = """You are an expert resume parser helping populate a \
structured career profile. You read raw resume text (possibly messy, \
extracted from a PDF or Word document) and extract every fact into the \
following JSON shape. Return ONLY a single JSON object (no markdown \
fences, no commentary):

{
  "profile": {
    "first_name": string,
    "last_name": string,
    "headline": string,
    "phone": string,
    "location": string,
    "bio": string,
    "linkedin_url": string,
    "portfolio_url": string,
    "github_url": string
  },
  "soft_skills": [
    {"name": string, "category": string, "level": "beginner" | "intermediate" | "advanced" | "expert"}
  ],
  "technical_skills": [
    {"name": string, "category": string, "level": "beginner" | "intermediate" | "advanced" | "expert"}
  ],
  "languages": [
    {"name": string, "proficiency": "basic" | "conversational" | "professional" | "fluent" | "native"}
  ],
  "experience": [
    {
      "job_title": string,
      "company": string,
      "location": string,
      "employment_type": "full_time" | "part_time" | "contract" | "freelance" | "internship" | "",
      "start_date": "YYYY-MM-DD" | null,
      "end_date": "YYYY-MM-DD" | null,
      "is_current": true | false,
      "highlights": [string]
    }
  ],
  "degrees": [
    {
      "school": string, "degree": string, "field_of_study": string,
      "start_date": "YYYY-MM-DD" | null, "end_date": "YYYY-MM-DD" | null,
      "is_current": true | false, "grade": string
    }
  ],
  "certificates": [
    {
      "name": string, "issuing_organization": string,
      "issue_date": "YYYY-MM-DD" | null, "expiry_date": "YYYY-MM-DD" | null,
      "does_not_expire": true | false, "credential_id": string, "credential_url": string
    }
  ]
}

Rules:
- Only extract what the resume actually states. Use "" (empty string), null, \
or an empty list for anything not mentioned — never invent facts.
- "headline" is a one-line professional summary (e.g. "Senior Backend Engineer \
specializing in distributed systems"), and "bio" is a short paragraph (2-4 \
sentences) summarizing their background, if the resume has a summary \
section — otherwise leave both blank rather than inventing one.
- Split each experience bullet into individual, atomic highlight statements.
- Dates: if only a month/year is given, use the 1st of that month. If only a \
year is given, use January 1st of that year. If a role/degree is ongoing, \
set is_current=true and leave end_date null.
- Classify each skill's level based on context (years of experience, how it's \
described, its position/emphasis in the resume) — default to \
"intermediate" if genuinely unclear.
- Do not list the same skill twice. Do not duplicate a language already \
covered by another entry.
"""


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
    categories_note = (
        "When choosing a `category` for each skill, prefer one of these existing "
        f"soft-skill categories where it reasonably fits: {', '.join(soft_categories) or '(none yet)'}.\n"
        "For technical skills, prefer one of these existing categories where it "
        f"reasonably fits: {', '.join(technical_categories) or '(none yet)'}.\n"
        "Only use a different category name if nothing listed is a reasonable fit."
    )
    user_content = (
        f"{language_clause(language)}\n\n{categories_note}\n\n"
        f"--- Resume text ---\n{truncated}"
    )
    return call_deepseek_json(SYSTEM_PROMPT, user_content)
