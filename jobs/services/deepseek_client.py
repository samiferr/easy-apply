"""Turns raw job-post text into structured data matching our JobPost /
RequirementCategory / Requirement schema, via the shared DeepSeek client.
"""

from core.ai import AIConfigError, AIServiceError, call_deepseek_json

# Kept as aliases so existing imports (e.g. jobs/services/importer.py)
# don't need to change.
DeepSeekError = AIServiceError
DeepSeekConfigError = AIConfigError

SYSTEM_PROMPT = """You are an expert job-post analyst. You read a raw job \
posting and extract structured information, the same way a careful \
candidate would triage it before deciding whether to apply. Focus on \
these sections, in this order of importance:

1. Job title + summary/overview (role, level, focus).
2. Responsibilities / what the person will actually do day to day.
3. Required qualifications / must-haves (skills, years of experience, \
education, certifications, specific technologies) — the true \
dealbreakers, not nice-to-haves.
4. Preferred / nice-to-have qualifications.
5. Location, work arrangement (remote/hybrid/on-site), time zone \
expectations, relocation, travel percentage.
6. Compensation & benefits: salary range, equity, bonus, health \
insurance, PTO, parental leave, professional development budget, etc.
7. Company/team information: size, stage (startup/scale-up/enterprise), \
industry, mission, who the role reports to.
8. Application instructions and any deadline.
9. Bonus signals: red flags (unrealistic requirement lists, vague \
responsibilities, "rockstar/ninja" language, pressure to apply \
immediately, reposted listings), growth/mentorship/impact language, and \
diversity/inclusion statements.

Return ONLY a single JSON object (no markdown fences, no commentary) with \
exactly this shape:

{
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
  "categories": [
    {
      "name": string,
      "type": "responsibilities" | "required" | "preferred" | "other",
      "requirements": [string]
    }
  ]
}

Rules:
- Only extract what the text actually states. Use "" (empty string), \
null, or an empty list for anything not mentioned — never invent facts.
- Split each responsibility/requirement bullet into individual, atomic \
statements (one clear idea per array item), even if the source combined \
several into one bullet.
- Always include a "responsibilities" category and a "required" category \
if the text has any content for them; include "preferred" only if the \
posting distinguishes nice-to-haves; use "other" for any extra grouping \
the posting itself uses (e.g. certifications) that doesn't fit the above.
- Do not include empty categories (an entry with zero requirements).
- salary_min/salary_max are plain numbers in the stated currency's base \
unit (no symbols, no commas), or null if no range is given.
- Keep string fields concise (a sentence or two); use "\\n" to separate \
multiple benefits/red flags only inside the array items, not within one \
item.
"""


def analyze_job_text(raw_text: str, source_url: str = "") -> dict:
    truncated = raw_text[:18000]
    user_content = (
        f"Job posting URL: {source_url or '(pasted manually)'}\n\n"
        f"--- Job posting text ---\n{truncated}"
    )
    return call_deepseek_json(SYSTEM_PROMPT, user_content)
