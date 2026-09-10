"""Orchestrates resume analysis (extract -> AI -> store) and turns a
user's selections from the review page into real Profile / UserSkill /
UserLanguage / WorkExperience+Highlights / Degree / Certificate rows.
"""

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from accounts.models import Profile
from core.ai import AIServiceError
from education.models import Certificate, Degree
from experience.models import ExperienceHighlight, WorkExperience
from languages.models import Language, UserLanguage
from skills.models import SkillCategory, UserSkill

from .deepseek_resume import analyze_resume_text
from .extractor import ResumeExtractError, extract_resume_text

logger = logging.getLogger(__name__)

LEVEL_MAP = {
    "beginner": UserSkill.BEGINNER,
    "intermediate": UserSkill.INTERMEDIATE,
    "advanced": UserSkill.ADVANCED,
    "expert": UserSkill.EXPERT,
}
PROFICIENCY_VALUES = {choice[0] for choice in UserLanguage.PROFICIENCY_CHOICES}
EMPLOYMENT_TYPES = {choice[0] for choice in WorkExperience.EMPLOYMENT_TYPE_CHOICES}

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


def _clean_str(value, max_length=None):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value[:max_length] if max_length else value


def _clean_list_of_dicts(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _clean_str_list(value):
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


# --- Pipeline: extract text, call the AI, store the result ------------------

def run_analysis(resume_import, progress=None) -> None:
    """Extract text from the uploaded file, call the AI, and store the
    result on `resume_import`. Always leaves it saved with a final status
    (completed or failed) — never raises.

    `progress` is the AITask driving this run, if any: step 1 is text
    extraction, step 2 is the AI parse.
    """
    resume_import.status = resume_import.STATUS_PROCESSING
    resume_import.save(update_fields=["status"])

    try:
        raw_text = extract_resume_text(resume_import.file)
        resume_import.raw_text = raw_text
        if progress is not None:
            progress.advance("Understanding your resume")

        soft_categories = list(
            SkillCategory.objects.filter(kind=SkillCategory.SOFT).values_list("name", flat=True)
        )
        technical_categories = list(
            SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).values_list(
                "name", flat=True
            )
        )
        # The AI call sits outside any transaction — see spec §7.1.
        data = analyze_resume_text(raw_text, soft_categories, technical_categories)

        resume_import.ai_response = data
        resume_import.ai_model = _clean_str(data.get("_model"), 100)
        resume_import.status = resume_import.STATUS_COMPLETED
        resume_import.analyzed_at = timezone.now()
        resume_import.error_message = ""
        resume_import.save(
            update_fields=[
                "raw_text", "ai_response", "ai_model", "status", "analyzed_at", "error_message",
            ]
        )
    except (ResumeExtractError, AIServiceError) as exc:
        resume_import.status = resume_import.STATUS_FAILED
        resume_import.error_message = str(exc)
        resume_import.save(update_fields=["status", "error_message", "raw_text"])
    except Exception:
        logger.exception("Unexpected error analyzing resume %s", resume_import.pk)
        resume_import.status = resume_import.STATUS_FAILED
        resume_import.error_message = "Something unexpected went wrong analyzing this resume."
        resume_import.save(update_fields=["status", "error_message"])


# --- Review: annotate the AI's suggestions with what's new vs. already-had --

def build_review_sections(resume_import, user) -> dict:
    data = resume_import.ai_response or {}
    profile_data = data.get("profile") or {}
    profile = getattr(user, "profile", None)

    profile_fields = []
    for field, label, max_length in PROFILE_FIELD_SPECS:
        current_value = user.first_name if field == "first_name" else (
            user.last_name if field == "last_name" else getattr(profile, field, "") if profile else ""
        )
        if current_value:
            continue
        value = _clean_str(profile_data.get(field), max_length)
        if not value:
            continue
        profile_fields.append({"key": f"profile:{field}", "label": label, "value": value})

    existing_skills = {
        (s.category.kind, s.name.lower()) for s in user.skills.select_related("category")
    }
    soft_skills, technical_skills = [], []
    for kind, section_key, prefix, bucket in (
        (SkillCategory.SOFT, "soft_skills", "soft_skill", soft_skills),
        (SkillCategory.TECHNICAL, "technical_skills", "technical_skill", technical_skills),
    ):
        for i, item in enumerate(_clean_list_of_dicts(data.get(section_key))):
            name = _clean_str(item.get("name"), 100)
            if not name:
                continue
            bucket.append({
                "key": f"{prefix}:{i}",
                "name": name,
                "category": _clean_str(item.get("category"), 100) or "Other",
                "level": (_clean_str(item.get("level")).lower() or "intermediate").capitalize(),
                "is_duplicate": (kind, name.lower()) in existing_skills,
            })

    existing_languages = {
        ul.language.name.lower() for ul in user.languages.select_related("language")
    }
    languages = []
    for i, item in enumerate(_clean_list_of_dicts(data.get("languages"))):
        name = _clean_str(item.get("name"), 80)
        if not name:
            continue
        proficiency = _clean_str(item.get("proficiency")).lower()
        languages.append({
            "key": f"language:{i}",
            "name": name,
            "proficiency": (proficiency if proficiency in PROFICIENCY_VALUES else "conversational").capitalize(),
            "is_duplicate": name.lower() in existing_languages,
        })

    existing_experience = {
        (e.company.lower(), e.job_title.lower()) for e in user.experiences.all()
    }
    experience = []
    for i, item in enumerate(_clean_list_of_dicts(data.get("experience"))):
        job_title = _clean_str(item.get("job_title"), 150)
        company = _clean_str(item.get("company"), 150)
        if not job_title or not company:
            continue
        experience.append({
            "key": f"experience:{i}",
            "job_title": job_title,
            "company": company,
            "location": _clean_str(item.get("location"), 120),
            "is_current": bool(item.get("is_current")),
            "start_date": item.get("start_date") or "",
            "end_date": "" if item.get("is_current") else (item.get("end_date") or ""),
            "highlights": _clean_str_list(item.get("highlights")),
            "is_duplicate": (company.lower(), job_title.lower()) in existing_experience,
        })

    existing_degrees = {(d.school.lower(), d.degree.lower()) for d in user.degrees.all()}
    degrees = []
    for i, item in enumerate(_clean_list_of_dicts(data.get("degrees"))):
        school = _clean_str(item.get("school"), 150)
        degree_name = _clean_str(item.get("degree"), 150)
        if not school or not degree_name:
            continue
        degrees.append({
            "key": f"degree:{i}",
            "school": school,
            "degree": degree_name,
            "field_of_study": _clean_str(item.get("field_of_study"), 150),
            "is_current": bool(item.get("is_current")),
            "start_date": item.get("start_date") or "",
            "end_date": "" if item.get("is_current") else (item.get("end_date") or ""),
            "is_duplicate": (school.lower(), degree_name.lower()) in existing_degrees,
        })

    existing_certificates = {
        (c.name.lower(), c.issuing_organization.lower()) for c in user.certificates.all()
    }
    certificates = []
    for i, item in enumerate(_clean_list_of_dicts(data.get("certificates"))):
        name = _clean_str(item.get("name"), 150)
        org = _clean_str(item.get("issuing_organization"), 150)
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


# --- Apply: create rows for whatever the user checked ------------------------

@transaction.atomic
def apply_selected(resume_import, user, selected_keys: set) -> dict:
    data = resume_import.ai_response or {}
    counts = {"profile": False, "skills": 0, "languages": 0, "experience": 0, "degrees": 0, "certificates": 0}

    profile_data = data.get("profile") or {}
    profile, _ = Profile.objects.get_or_create(user=user)

    if "profile:first_name" in selected_keys or "profile:last_name" in selected_keys:
        if "profile:first_name" in selected_keys:
            user.first_name = _clean_str(profile_data.get("first_name"), 150) or user.first_name
        if "profile:last_name" in selected_keys:
            user.last_name = _clean_str(profile_data.get("last_name"), 150) or user.last_name
        user.save(update_fields=["first_name", "last_name"])
        counts["profile"] = True

    profile_update_fields = []
    for field, _label, max_length in PROFILE_FIELD_SPECS:
        if field in ("first_name", "last_name"):
            continue
        key = f"profile:{field}"
        if key in selected_keys:
            value = _clean_str(profile_data.get(field), max_length)
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
        for i, item in enumerate(_clean_list_of_dicts(data.get(section_key))):
            key = f"{prefix}:{i}"
            if key not in selected_keys:
                continue
            name = _clean_str(item.get("name"), 100)
            if not name:
                continue
            category_name = _clean_str(item.get("category"), 100) or "Other"
            category, _ = SkillCategory.objects.get_or_create(name=category_name, kind=kind)
            level = LEVEL_MAP.get(_clean_str(item.get("level")).lower(), UserSkill.INTERMEDIATE)
            _, created = UserSkill.objects.get_or_create(
                user=user, category=category, name=name, defaults={"level": level}
            )
            if created:
                counts["skills"] += 1

    for i, item in enumerate(_clean_list_of_dicts(data.get("languages"))):
        key = f"language:{i}"
        if key not in selected_keys:
            continue
        name = _clean_str(item.get("name"), 80)
        if not name:
            continue
        proficiency = _clean_str(item.get("proficiency")).lower()
        if proficiency not in PROFICIENCY_VALUES:
            proficiency = UserLanguage.CONVERSATIONAL
        language, _ = Language.objects.get_or_create(
            name__iexact=name, defaults={"name": name}
        )
        _, created = UserLanguage.objects.get_or_create(
            user=user, language=language, defaults={"proficiency": proficiency}
        )
        if created:
            counts["languages"] += 1

    for i, item in enumerate(_clean_list_of_dicts(data.get("experience"))):
        key = f"experience:{i}"
        if key not in selected_keys:
            continue
        job_title = _clean_str(item.get("job_title"), 150)
        company = _clean_str(item.get("company"), 150)
        if not job_title or not company:
            continue
        employment_type = _clean_str(item.get("employment_type")).lower()
        if employment_type not in EMPLOYMENT_TYPES:
            employment_type = ""
        is_current = bool(item.get("is_current"))
        experience = WorkExperience.objects.create(
            user=user,
            job_title=job_title,
            company=company,
            location=_clean_str(item.get("location"), 120),
            employment_type=employment_type,
            start_date=_parse_date(item.get("start_date")) or timezone.localdate(),
            end_date=None if is_current else _parse_date(item.get("end_date")),
            is_current=is_current,
        )
        ExperienceHighlight.objects.bulk_create(
            ExperienceHighlight(experience=experience, text=text[:500], order=order)
            for order, text in enumerate(_clean_str_list(item.get("highlights")))
        )
        counts["experience"] += 1

    for i, item in enumerate(_clean_list_of_dicts(data.get("degrees"))):
        key = f"degree:{i}"
        if key not in selected_keys:
            continue
        school = _clean_str(item.get("school"), 150)
        degree_name = _clean_str(item.get("degree"), 150)
        if not school or not degree_name:
            continue
        is_current = bool(item.get("is_current"))
        Degree.objects.create(
            user=user,
            school=school,
            degree=degree_name,
            field_of_study=_clean_str(item.get("field_of_study"), 150),
            start_date=_parse_date(item.get("start_date")),
            end_date=None if is_current else _parse_date(item.get("end_date")),
            is_current=is_current,
            grade=_clean_str(item.get("grade"), 50),
        )
        counts["degrees"] += 1

    for i, item in enumerate(_clean_list_of_dicts(data.get("certificates"))):
        key = f"certificate:{i}"
        if key not in selected_keys:
            continue
        name = _clean_str(item.get("name"), 150)
        org = _clean_str(item.get("issuing_organization"), 150)
        if not name or not org:
            continue
        does_not_expire = bool(item.get("does_not_expire"))
        Certificate.objects.create(
            user=user,
            name=name,
            issuing_organization=org,
            issue_date=_parse_date(item.get("issue_date")),
            expiry_date=None if does_not_expire else _parse_date(item.get("expiry_date")),
            does_not_expire=does_not_expire,
            credential_id=_clean_str(item.get("credential_id"), 100),
            credential_url=_clean_str(item.get("credential_url"), 200),
        )
        counts["certificates"] += 1

    resume_import.status = resume_import.STATUS_APPLIED
    resume_import.applied_at = timezone.now()
    resume_import.save(update_fields=["status", "applied_at"])

    return counts
