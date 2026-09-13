"""Drafts a job-specific resume for a user, as Markdown.

The AI is asked for the *content* of each resume section (rewritten to
speak the job's language, ordered by what that job asks for) as JSON; the
document itself is then assembled here, following the section skeleton in
`templates/resume_template.md`, so the layout — and the contact details in
the header — never depend on the model getting them right.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.ai import AIServiceError, call_deepseek_json
from core.language import language_clause, use_language
from core.utils import build_resume_snapshot, profile_snapshot_is_empty

from ..models import TailoredResume

logger = logging.getLogger(__name__)

TEMPLATE_PATH = settings.BASE_DIR / "templates" / "resume_template.md"

SUMMARY = "summary"
SKILLS = "skills"
EXPERIENCE = "experience"
EDUCATION = "education"
LANGUAGES = "languages"

# Used when templates/resume_template.md is missing or has no usable headings.
DEFAULT_SECTIONS = [
    (SUMMARY, "PROFESSIONAL SUMMARY"),
    (SKILLS, "SKILLS"),
    (EXPERIENCE, "WORKING EXPERIENCE"),
    (EDUCATION, "EDUCATION & PROFESSIONAL DEVELOPMENT"),
    (LANGUAGES, "LANGUAGES"),
]

#: The headings we print, per content key. `resume_template.md` decides which
#: sections appear and in what order; these decide what they are *called*, so a
#: French profile gets a French resume rather than French prose under English
#: headings.
SECTION_HEADINGS = {
    SUMMARY: _("PROFESSIONAL SUMMARY"),
    SKILLS: _("SKILLS"),
    EXPERIENCE: _("WORKING EXPERIENCE"),
    EDUCATION: _("EDUCATION & PROFESSIONAL DEVELOPMENT"),
    LANGUAGES: _("LANGUAGES"),
}

SYSTEM_PROMPT = """You are an expert resume writer. You are given a JSON \
object with three keys: "job" (a structured job posting, including every \
requirement extracted from it and — when available — whether the \
candidate's profile already matches that requirement), \
"candidate_profile" (everything the candidate has recorded: skills, \
languages, work experience with highlight bullets, degrees and \
certificates) and "resume_template" (the Markdown skeleton the finished \
resume must fill).

Write the content of a one-to-two page resume tailored to that job. \
Return ONLY a single JSON object (no markdown fences, no commentary) with \
this shape:

{
  "professional_summary": string,
  "skills": [{"group": string, "items": [string]}],
  "experience": [
    {
      "job_title": string, "company": string, "location": string,
      "dates": string, "highlights": [string]
    }
  ],
  "education": [
    {"title": string, "organization": string, "dates": string, "details": string}
  ],
  "languages": [string]
}

Rules:
- Use ONLY facts present in "candidate_profile". Never invent an employer, \
a date, a degree, a certificate, a tool or a metric the candidate did not \
record. Do not upgrade a skill's level or stretch a date range.
- Copy "job_title", "company", "location" and "dates" verbatim from the \
matching profile entry — they are facts, not prose.
- Include every role in "experience", most recent first, but spend the \
most bullets (4-6) on the roles closest to this job and fewer (1-3) on \
distant ones. Rewrite each highlight in the job's own vocabulary, keeping \
it truthful, starting with a strong action verb, and one or two lines long.
- "professional_summary" is 2-4 sentences positioning the candidate for \
THIS job, naming their strongest genuinely-matching qualifications.
- "skills" groups the candidate's real skills under short headings (e.g. \
"Programming", "Cloud & DevOps", "Soft skills"), listing first the ones \
this job asks for. Never add a skill the candidate hasn't recorded.
- "education" covers degrees first, then certificates; "details" is a \
short optional line (field of study, grade, credential id) or "".
- "languages" is a list of short strings like "French — Native".
- Where a requirement is marked as not covered by the profile, do not \
paper over it with an invented claim — simply lead with the evidence the \
candidate does have.
"""


def _clean_str(value, max_length=None) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value[:max_length] if max_length else value


def _clean_str_list(value, max_length=None) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [_clean_str(item, max_length) for item in value]
    return [item for item in cleaned if item]


def _clean_dict_list(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _section_key(heading: str) -> str:
    """Map a heading from the template file onto the content we generate."""

    text = heading.upper()
    if "SUMMARY" in text or "PROFILE" in text or "OBJECTIVE" in text:
        return SUMMARY
    if "SKILL" in text:
        return SKILLS
    if "EDUCATION" in text or "CERTIFICAT" in text or "DEVELOPMENT" in text:
        return EDUCATION
    if "EXPERIENCE" in text or "EMPLOYMENT" in text or "WORK" in text:
        return EXPERIENCE
    if "LANGUAGE" in text:
        return LANGUAGES
    return ""


def load_template_text() -> str:
    """The raw resume_template.md, or "" if it isn't readable."""

    try:
        return TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Resume template not found at %s", TEMPLATE_PATH)
        return ""


def load_template_sections() -> list[tuple[str, str]]:
    """Read the `##` headings out of resume_template.md, in order, as
    (content key, heading text) pairs — so editing that file changes the
    shape of every generated resume."""

    sections: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in load_template_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("##"):
            continue
        heading = stripped.lstrip("#").strip().strip("*").strip()
        if not heading:
            continue
        key = _section_key(heading)
        if not key or key in seen:
            continue
        seen.add(key)
        sections.append((key, heading))
    return sections or list(DEFAULT_SECTIONS)


def build_job_payload(job) -> dict:
    """The job as the resume writer needs to see it: the posting's own
    framing plus every requirement, tagged with how the user's profile
    matched it (when "Match to my profile" has already been run)."""

    requirements = []
    for section in job.sections.prefetch_related("elements"):
        if not section.is_matched_section:
            continue
        label = str(section.label)
        for element in section.elements.all():
            entry = {"category": label, "text": element.text}
            if element.match_status:
                entry["profile_match"] = element.match_status
                entry["match_evidence"] = element.match_evidence
            requirements.append(entry)

    return {
        "title": job.title,
        "company": job.company_name,
        "seniority_level": job.seniority_level,
        "summary": job.summary,
        "location": job.location,
        "work_arrangement": job.get_work_arrangement_display() if job.work_arrangement else "",
        "requirements": requirements,
    }


# --- Markdown assembly ------------------------------------------------------


def _header_lines(profile) -> list[str]:
    user = profile.user
    name = user.get_full_name() or user.get_short_name()
    contact_bits = [profile.location, profile.phone, user.email]
    lines = [f"**{name}**", ""]
    contact = "  |  ".join(bit for bit in contact_bits if bit)
    if contact:
        lines.append(contact)
    links = [
        url
        for url in (profile.linkedin_url, profile.portfolio_url, profile.github_url)
        if url
    ]
    if links:
        lines.append("  |  ".join(links))
    return lines


def _summary_lines(data, profile) -> list[str]:
    summary = _clean_str(data.get("professional_summary"))
    return [summary] if summary else []


def _skills_lines(data, profile) -> list[str]:
    lines = []
    for group in _clean_dict_list(data.get("skills")):
        items = _clean_str_list(group.get("items"), 120)
        if not items:
            continue
        name = _clean_str(group.get("group"), 60)
        lines.append(f"- **{name}:** {', '.join(items)}" if name else f"- {', '.join(items)}")
    return lines


def _experience_lines(data, profile) -> list[str]:
    lines = []
    for role in _clean_dict_list(data.get("experience")):
        job_title = _clean_str(role.get("job_title"), 150)
        company = _clean_str(role.get("company"), 150)
        if not job_title and not company:
            continue
        heading = " — ".join(
            bit for bit in (f"**{job_title}**" if job_title else "", company) if bit
        )
        if lines:
            lines.append("")
        lines.append(f"### {heading}")
        meta = " · ".join(
            bit
            for bit in (_clean_str(role.get("dates"), 60), _clean_str(role.get("location"), 120))
            if bit
        )
        if meta:
            lines.append(f"*{meta}*")
            lines.append("")
        for highlight in _clean_str_list(role.get("highlights"), 500):
            lines.append(f"- {highlight}")
    return lines


def _education_lines(data, profile) -> list[str]:
    lines = []
    for entry in _clean_dict_list(data.get("education")):
        title = _clean_str(entry.get("title"), 150)
        organization = _clean_str(entry.get("organization"), 150)
        if not title and not organization:
            continue
        heading = " — ".join(
            bit for bit in (f"**{title}**" if title else "", organization) if bit
        )
        if lines:
            lines.append("")
        lines.append(f"### {heading}")
        meta = " · ".join(
            bit
            for bit in (_clean_str(entry.get("dates"), 60), _clean_str(entry.get("details"), 300))
            if bit
        )
        if meta:
            lines.append(f"*{meta}*")
    return lines


def _languages_lines(data, profile) -> list[str]:
    return [f"- {language}" for language in _clean_str_list(data.get("languages"), 120)]


SECTION_BUILDERS = {
    SUMMARY: _summary_lines,
    SKILLS: _skills_lines,
    EXPERIENCE: _experience_lines,
    EDUCATION: _education_lines,
    LANGUAGES: _languages_lines,
}


def render_markdown(profile, data: dict, sections=None) -> str:
    """Assemble the AI's section content into one Markdown document laid
    out like resume_template.md. Sections the AI returned nothing for are
    left out rather than printed as an empty heading.

    Headings are rendered in the profile's language, matching the prose the
    model was told to write.
    """

    sections = sections if sections is not None else load_template_sections()
    lines = _header_lines(profile)

    with use_language(profile.language):
        for key, heading in sections:
            builder = SECTION_BUILDERS.get(key)
            if builder is None:
                continue
            body = builder(data, profile)
            if not body:
                continue
            label = SECTION_HEADINGS.get(key)
            lines.extend(["", f"## **{label or heading}**", ""])
            lines.extend(body)

    return "\n".join(lines).strip() + "\n"


# --- Entry point ------------------------------------------------------------


def generate_tailored_resume(job, profile=None) -> dict:
    """Draft (or re-draft) the tailored resume for `job` and store it as
    editable Markdown. Returns {"skipped": "empty_profile"} when there's
    nothing to write about, otherwise {"tailored_resume": <row>}. Raises
    AIServiceError on failure."""

    profile = profile or job.profile
    with use_language(profile.language):
        # The snapshot carries display strings (levels, proficiencies, dates)
        # straight into the prompt, so build it in the profile's language.
        profile_snapshot = build_resume_snapshot(profile)
        empty_message = str(
            _("Add some experience or skills to this profile first.")
        )
    if profile_snapshot_is_empty(profile_snapshot):
        TailoredResume.objects.filter(job=job).update(
            state=TailoredResume.STATE_FAILED,
            error_message=empty_message,
        )
        return {"skipped": "empty_profile"}

    with use_language(profile.language):
        job_payload = build_job_payload(job)
    payload = json.dumps(
        {
            "job": job_payload,
            "candidate_profile": profile_snapshot,
            "resume_template": load_template_text(),
        },
        # Accented profile content reaches the model as text, not as \uXXXX
        # escapes — same as the matcher's payload.
        ensure_ascii=False,
    )
    user_content = f"{language_clause(profile.language)}\n\n{payload}"
    data = call_deepseek_json(SYSTEM_PROMPT, user_content, temperature=0.3)

    markdown = render_markdown(profile, data)
    if not markdown.strip():
        raise AIServiceError("The AI resume writer returned an empty resume.")

    tailored_resume, _created = TailoredResume.objects.update_or_create(
        job=job,
        defaults={
            "profile": profile,
            "markdown": markdown,
            "ai_model": _clean_str(data.get("_model"), 100),
            "edited_by_user": False,
            "state": TailoredResume.STATE_COMPLETED,
            "error_message": "",
            "generated_at": timezone.now(),
        },
    )
    return {"tailored_resume": tailored_resume}
