"""Use cases of resumes: importing one into a profile, and writing one for a job.

Two independent flows share the app.

* **Import (UC-04).** The candidate uploads a PDF, DOCX or TXT; the AI reads it
  in the background (`resume/tasks.py`, `resume/domain/importer.py`); the review
  page lists what it found and marks what the profile already has; applying the
  ticked items creates the rows, all or nothing.
* **Tailored resume (UC-07).** From an analysed job post the AI drafts a
  Markdown resume out of the profile and the job's requirements; the candidate
  edits it, downloads it as PDF or Markdown, or deletes it.

Views call the functions below and only translate the outcome: a `Blocked` or
`PreconditionFailed` becomes a flash message, and the response is a redirect or
a file. Everything is scoped to the active profile, so a resume, an import and a
job of another workspace are a 404.

Use cases: docs/use-cases/UC04_RESUME_PARSING_ONBOARDING.md and
UC07_TAILORED_RESUME_GENERATION.md.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from core.exceptions import Blocked, PreconditionFailed
from core.models import AITask
from education.models import Certificate, Degree
from experience.models import ExperienceHighlight, WorkExperience
from jobs.models import JobPost
from languages.models import Language, UserLanguage
from skills.models import SkillCategory, UserSkill
from staffportal.domain import quotas
from staffportal.models import UsageMetric

from .domain.importer import clean_list_of_dicts, clean_str, clean_str_list, parse_date
from .domain.pdf import render_markdown_pdf
from .models import ResumeImport, TailoredResume
from .tasks import enqueue_resume_analysis, enqueue_tailored_resume

#: What the AI may call a skill level, and the level it becomes. The parse
#: prompt (`prompts/resume/parse_resume.txt`) offers exactly these words.
LEVEL_MAP = {
    "beginner": UserSkill.BEGINNER,
    "intermediate": UserSkill.INTERMEDIATE,
    "advanced": UserSkill.ADVANCED,
    "expert": UserSkill.EXPERT,
}
PROFICIENCY_VALUES = {choice[0] for choice in UserLanguage.PROFICIENCY_CHOICES}
EMPLOYMENT_TYPES = {choice[0] for choice in WorkExperience.EMPLOYMENT_TYPE_CHOICES}

#: The profile fields a resume can fill in: (key, label, max length).
PROFILE_FIELD_SPECS = [
    ("first_name", "First name", 150),
    ("last_name", "Last name", 150),
    ("headline", "Headline", 150),
    ("phone", "Phone", 30),
    ("location", "Location", 120),
    ("bio", "About me", 2000),
    ("linkedin_url", "LinkedIn", 200),
    ("portfolio_url", "Portfolio", 200),
    ("github_url", "GitHub", 200),
]


# ---------------------------------------------------------------------------
# UC-04 / UC-07 — the workspace boundary
# ---------------------------------------------------------------------------
def profile_imports(profile):
    return ResumeImport.objects.filter(profile=profile)


def profile_tailored_resumes(profile):
    return TailoredResume.objects.filter(profile=profile)


# UC-07 — the list of drafts, each addressed by the job it was written for
def list_tailored_resumes(profile):
    return profile_tailored_resumes(profile).select_related("job")


# ---------------------------------------------------------------------------
# UC-04 — Resume parsing & onboarding
# ---------------------------------------------------------------------------
# UC-04.1 — Multi-Format Resume Upload & Quota Validation (steps 3-6)
def start_resume_import(user, profile, form) -> ResumeImport:
    """Save the upload a validated `ResumeUploadForm` holds and queue its analysis.

    The allowance is checked before anything is written and consumed once the
    work is queued; the caller never waits on the AI — the review page shows
    progress. Raises `Blocked` (quota exhausted or the AI switched off).
    """
    blocked = quotas.blocked_message(user, UsageMetric.RESUME_IMPORT)
    if blocked:
        raise Blocked(blocked)

    form.instance.profile = profile
    form.instance.original_filename = form.instance.file.name
    resume_import = form.save()
    enqueue_resume_analysis(resume_import)
    quotas.consume(user, UsageMetric.RESUME_IMPORT)
    return resume_import


# UC-04.2 — step 8: the task the review page follows while the resume is read
def import_task(resume_import: ResumeImport) -> AITask | None:
    return AITask.latest_for(resume_import, AITask.RESUME_IMPORT)


# UC-04.3 — step 2: the checklist only exists once the AI has read the resume
def is_reviewable(resume_import: ResumeImport) -> bool:
    return resume_import.status == ResumeImport.STATUS_COMPLETED


# UC-04.3 — step 2
def review_checklist(resume_import: ResumeImport, profile) -> dict | None:
    """`build_review_sections` for a resume that has been read, None until then."""
    if not is_reviewable(resume_import):
        return None
    return build_review_sections(resume_import, profile)


# UC-04.3 — Intelligent Collision & Duplicate Detection (steps 2-4)
def build_review_sections(resume_import, profile) -> dict:
    """The checklist the review page shows: what the AI found, section by section,
    each item marked `is_duplicate` when the profile already has it, and the
    profile fields it would fill in only where the profile has none."""
    data = resume_import.ai_response or {}
    profile_data = data.get("profile") or {}
    user = profile.user

    profile_fields = []
    for field, label, max_length in PROFILE_FIELD_SPECS:
        current_value = user.first_name if field == "first_name" else (
            user.last_name if field == "last_name" else getattr(profile, field, "")
        )
        if current_value:
            continue
        value = clean_str(profile_data.get(field), max_length)
        if not value:
            continue
        profile_fields.append({"key": f"profile:{field}", "label": label, "value": value})

    existing_skills = {
        (s.category.kind, s.name.lower()) for s in profile.skills.select_related("category")
    }
    soft_skills, technical_skills = [], []
    for kind, section_key, prefix, bucket in (
        (SkillCategory.SOFT, "soft_skills", "soft_skill", soft_skills),
        (SkillCategory.TECHNICAL, "technical_skills", "technical_skill", technical_skills),
    ):
        for i, item in enumerate(clean_list_of_dicts(data.get(section_key))):
            name = clean_str(item.get("name"), 100)
            if not name:
                continue
            bucket.append({
                "key": f"{prefix}:{i}",
                "name": name,
                "category": clean_str(item.get("category"), 100) or "Other",
                "level": (clean_str(item.get("level")).lower() or "intermediate").capitalize(),
                "is_duplicate": (kind, name.lower()) in existing_skills,
            })

    existing_languages = {
        ul.language.name.lower() for ul in profile.languages.select_related("language")
    }
    languages = []
    for i, item in enumerate(clean_list_of_dicts(data.get("languages"))):
        name = clean_str(item.get("name"), 80)
        if not name:
            continue
        proficiency = clean_str(item.get("proficiency")).lower()
        languages.append({
            "key": f"language:{i}",
            "name": name,
            "proficiency": (proficiency if proficiency in PROFICIENCY_VALUES else "conversational").capitalize(),
            "is_duplicate": name.lower() in existing_languages,
        })

    existing_experience = {
        (e.company.lower(), e.job_title.lower()) for e in profile.experiences.all()
    }
    experience = []
    for i, item in enumerate(clean_list_of_dicts(data.get("experience"))):
        job_title = clean_str(item.get("job_title"), 150)
        company = clean_str(item.get("company"), 150)
        if not job_title or not company:
            continue
        experience.append({
            "key": f"experience:{i}",
            "job_title": job_title,
            "company": company,
            "location": clean_str(item.get("location"), 120),
            "is_current": bool(item.get("is_current")),
            "start_date": item.get("start_date") or "",
            "end_date": "" if item.get("is_current") else (item.get("end_date") or ""),
            "highlights": clean_str_list(item.get("highlights")),
            "is_duplicate": (company.lower(), job_title.lower()) in existing_experience,
        })

    existing_degrees = {(d.school.lower(), d.degree.lower()) for d in profile.degrees.all()}
    degrees = []
    for i, item in enumerate(clean_list_of_dicts(data.get("degrees"))):
        school = clean_str(item.get("school"), 150)
        degree_name = clean_str(item.get("degree"), 150)
        if not school or not degree_name:
            continue
        degrees.append({
            "key": f"degree:{i}",
            "school": school,
            "degree": degree_name,
            "field_of_study": clean_str(item.get("field_of_study"), 150),
            "is_current": bool(item.get("is_current")),
            "start_date": item.get("start_date") or "",
            "end_date": "" if item.get("is_current") else (item.get("end_date") or ""),
            "is_duplicate": (school.lower(), degree_name.lower()) in existing_degrees,
        })

    existing_certificates = {
        (c.name.lower(), c.issuing_organization.lower()) for c in profile.certificates.all()
    }
    certificates = []
    for i, item in enumerate(clean_list_of_dicts(data.get("certificates"))):
        name = clean_str(item.get("name"), 150)
        org = clean_str(item.get("issuing_organization"), 150)
        if not name or not org:
            continue
        certificates.append({
            "key": f"certificate:{i}",
            "name": name,
            "issuing_organization": org,
            "issue_date": item.get("issue_date") or "",
            "does_not_expire": bool(item.get("does_not_expire")),
            "is_duplicate": (name.lower(), org.lower()) in existing_certificates,
        })

    return {
        "profile_fields": profile_fields,
        "soft_skills": soft_skills,
        "technical_skills": technical_skills,
        "languages": languages,
        "experience": experience,
        "degrees": degrees,
        "certificates": certificates,
    }


# UC-04.4 — Interactive Review Checklist & Transactional Selective Import (step 4)
@transaction.atomic
def apply_selected(resume_import, profile, selected_keys: set) -> dict:
    """Create the rows for the items whose keys the candidate ticked, all or
    nothing, and mark the upload applied. Returns how many of each were added."""
    data = resume_import.ai_response or {}
    counts = {"profile": False, "skills": 0, "languages": 0, "experience": 0, "degrees": 0, "certificates": 0}

    profile_data = data.get("profile") or {}
    user = profile.user

    if "profile:first_name" in selected_keys or "profile:last_name" in selected_keys:
        if "profile:first_name" in selected_keys:
            user.first_name = clean_str(profile_data.get("first_name"), 150) or user.first_name
        if "profile:last_name" in selected_keys:
            user.last_name = clean_str(profile_data.get("last_name"), 150) or user.last_name
        user.save(update_fields=["first_name", "last_name"])
        counts["profile"] = True

    profile_update_fields = []
    for field, _label, max_length in PROFILE_FIELD_SPECS:
        if field in ("first_name", "last_name"):
            continue
        key = f"profile:{field}"
        if key in selected_keys:
            value = clean_str(profile_data.get(field), max_length)
            if value:
                setattr(profile, field, value)
                profile_update_fields.append(field)
    if profile_update_fields:
        profile.save(update_fields=profile_update_fields)
        counts["profile"] = True

    for kind, section_key, prefix in (
        (SkillCategory.SOFT, "soft_skills", "soft_skill"),
        (SkillCategory.TECHNICAL, "technical_skills", "technical_skill"),
    ):
        for i, item in enumerate(clean_list_of_dicts(data.get(section_key))):
            key = f"{prefix}:{i}"
            if key not in selected_keys:
                continue
            name = clean_str(item.get("name"), 100)
            if not name:
                continue
            category_name = clean_str(item.get("category"), 100) or "Other"
            category, _ = SkillCategory.objects.get_or_create(name=category_name, kind=kind)
            level = LEVEL_MAP.get(clean_str(item.get("level")).lower(), UserSkill.INTERMEDIATE)
            _, created = UserSkill.objects.get_or_create(
                profile=profile, category=category, name=name, defaults={"level": level}
            )
            if created:
                counts["skills"] += 1

    for i, item in enumerate(clean_list_of_dicts(data.get("languages"))):
        key = f"language:{i}"
        if key not in selected_keys:
            continue
        name = clean_str(item.get("name"), 80)
        if not name:
            continue
        proficiency = clean_str(item.get("proficiency")).lower()
        if proficiency not in PROFICIENCY_VALUES:
            proficiency = UserLanguage.CONVERSATIONAL
        language, _ = Language.objects.get_or_create(
            name__iexact=name, defaults={"name": name}
        )
        _, created = UserLanguage.objects.get_or_create(
            profile=profile, language=language, defaults={"proficiency": proficiency}
        )
        if created:
            counts["languages"] += 1

    for i, item in enumerate(clean_list_of_dicts(data.get("experience"))):
        key = f"experience:{i}"
        if key not in selected_keys:
            continue
        job_title = clean_str(item.get("job_title"), 150)
        company = clean_str(item.get("company"), 150)
        if not job_title or not company:
            continue
        employment_type = clean_str(item.get("employment_type")).lower()
        if employment_type not in EMPLOYMENT_TYPES:
            employment_type = ""
        is_current = bool(item.get("is_current"))
        experience = WorkExperience.objects.create(
            profile=profile,
            job_title=job_title,
            company=company,
            location=clean_str(item.get("location"), 120),
            employment_type=employment_type,
            start_date=parse_date(item.get("start_date")) or timezone.localdate(),
            end_date=None if is_current else parse_date(item.get("end_date")),
            is_current=is_current,
        )
        ExperienceHighlight.objects.bulk_create(
            ExperienceHighlight(experience=experience, text=text[:500], order=order)
            for order, text in enumerate(clean_str_list(item.get("highlights")))
        )
        counts["experience"] += 1

    for i, item in enumerate(clean_list_of_dicts(data.get("degrees"))):
        key = f"degree:{i}"
        if key not in selected_keys:
            continue
        school = clean_str(item.get("school"), 150)
        degree_name = clean_str(item.get("degree"), 150)
        if not school or not degree_name:
            continue
        is_current = bool(item.get("is_current"))
        Degree.objects.create(
            profile=profile,
            school=school,
            degree=degree_name,
            field_of_study=clean_str(item.get("field_of_study"), 150),
            start_date=parse_date(item.get("start_date")),
            end_date=None if is_current else parse_date(item.get("end_date")),
            is_current=is_current,
            grade=clean_str(item.get("grade"), 50),
        )
        counts["degrees"] += 1

    for i, item in enumerate(clean_list_of_dicts(data.get("certificates"))):
        key = f"certificate:{i}"
        if key not in selected_keys:
            continue
        name = clean_str(item.get("name"), 150)
        org = clean_str(item.get("issuing_organization"), 150)
        if not name or not org:
            continue
        does_not_expire = bool(item.get("does_not_expire"))
        Certificate.objects.create(
            profile=profile,
            name=name,
            issuing_organization=org,
            issue_date=parse_date(item.get("issue_date")),
            expiry_date=None if does_not_expire else parse_date(item.get("expiry_date")),
            does_not_expire=does_not_expire,
            credential_id=clean_str(item.get("credential_id"), 100),
            credential_url=clean_str(item.get("credential_url"), 200),
        )
        counts["certificates"] += 1

    resume_import.status = resume_import.STATUS_APPLIED
    resume_import.applied_at = timezone.now()
    resume_import.save(update_fields=["status", "applied_at"])

    return counts


# UC-04.4 — Interactive Review Checklist & Transactional Selective Import (steps 3-6)
def apply_review(resume_import: ResumeImport, profile, selected_keys: set) -> str:
    """Import what the candidate ticked and return the sentence that says what
    was added. Raises `PreconditionFailed` when nothing is ticked."""
    if not selected_keys:
        raise PreconditionFailed(gettext("Select at least one item to add it to your profile."))
    counts = apply_selected(resume_import, profile, selected_keys)
    return import_summary(counts)


# UC-04.4 — step 6: "Updated 8 skill(s), 2 work experience entries from your resume."
def import_summary(counts: dict) -> str:
    added = [
        f"{counts['skills']} skill(s)" if counts["skills"] else None,
        f"{counts['languages']} language(s)" if counts["languages"] else None,
        f"{counts['experience']} work experience entr{'y' if counts['experience'] == 1 else 'ies'}"
        if counts["experience"]
        else None,
        f"{counts['degrees']} degree(s)" if counts["degrees"] else None,
        f"{counts['certificates']} certificate(s)" if counts["certificates"] else None,
    ]
    added = [item for item in added if item]
    if counts["profile"]:
        added.insert(0, "your profile")
    summary = ", ".join(added) if added else "nothing new"
    return f"Updated {summary} from your resume."


# ---------------------------------------------------------------------------
# UC-07 — Job-tailored resumes
# ---------------------------------------------------------------------------
# UC-07.1 — AI Generation of Job-Tailored Resume Draft (preconditions 1-3, steps 3-6)
def start_tailored_resume(user, job: JobPost) -> AITask:
    """Queue the draft (or re-draft) of the resume for an analysed job and spend
    one allowance. Raises `PreconditionFailed` for a job that has not been
    analysed and `Blocked` when the plan or the AI switch does not allow it."""
    if job.status != JobPost.STATUS_COMPLETED:
        raise PreconditionFailed(
            gettext("Analyze this job post first, then generate a resume for it.")
        )

    blocked = quotas.blocked_message(user, UsageMetric.TAILORED_RESUME)
    if blocked:
        raise Blocked(blocked)

    task = enqueue_tailored_resume(job)
    quotas.consume(user, UsageMetric.TAILORED_RESUME)
    return task


# UC-07.1 — step 7: the task the editor follows until the draft is ready
def tailored_resume_task(tailored_resume: TailoredResume) -> AITask | None:
    return AITask.latest_for(tailored_resume, AITask.TAILORED_RESUME)


# UC-07.2 — Interactive Markdown In-Browser Editing & Modification Tracking (step 5)
def save_tailored_edits(form) -> TailoredResume:
    """Save a validated `TailoredResumeForm`. Once the text differs from what the
    AI drafted, the resume is marked as edited by the candidate."""
    if form.has_changed():
        form.instance.edited_by_user = True
    return form.save()


# UC-07.3 — ReportLab PDF Compilation with Strict Language Formatting (step 3)
def tailored_resume_pdf(tailored_resume: TailoredResume) -> bytes:
    return render_markdown_pdf(
        tailored_resume.markdown,
        title=tailored_resume.job.title or "Resume",
        author=tailored_resume.profile.user.get_full_name(),
    )


# UC-07.4 — Raw Markdown Export & Tailored Resume Lifecycle (deletion, step 4):
# the job post stays
def remove_tailored_resume(tailored_resume: TailoredResume) -> None:
    tailored_resume.delete()
