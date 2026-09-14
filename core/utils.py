"""Utilities to render a Markdown recap of everything a profile has recorded.

Every string this module emits — headings, "Present", month names — is
translatable and rendered under the profile's own language, so a recap (and the
resume snapshot built from the same helpers) never mixes two languages.
"""

from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .language import use_language


def _format_date(value, fmt="F Y"):
    return date_format(value, fmt) if value else ""


def _section(lines, title, level=2):
    lines.append("")
    lines.append(f"{'#' * level} {title}")


def generate_markdown_recap(profile) -> str:
    """Build a single Markdown document summarizing one profile's info, skills,
    languages, work experience, degrees and certificates.

    Rendered under the profile's own language, so its labels, month names and
    "Present" markers match the content recorded in it.
    """

    with use_language(profile.language):
        return _recap_lines(profile)


def _recap_lines(profile) -> str:
    """The recap body. Always called inside the profile's language."""
    lines: list[str] = []

    user = profile.user
    full_name = user.get_full_name() or user.get_short_name()

    lines.append(f"# {full_name}")
    if profile.headline:
        lines.append(f"*{profile.headline}*")

    lines.append("")
    contact_bits = [f"- **{_('Email')}:** {user.email}"]
    if profile.phone:
        contact_bits.append(f"- **{_('Phone')}:** {profile.phone}")
    if profile.location:
        contact_bits.append(f"- **{_('Location')}:** {profile.location}")
    if profile.linkedin_url:
        contact_bits.append(f"- **{_('LinkedIn')}:** {profile.linkedin_url}")
    if profile.portfolio_url:
        contact_bits.append(f"- **{_('Portfolio')}:** {profile.portfolio_url}")
    if profile.github_url:
        contact_bits.append(f"- **{_('GitHub')}:** {profile.github_url}")
    lines.extend(contact_bits)

    if profile.bio:
        _section(lines, _("About"))
        lines.append("")
        lines.append(profile.bio.strip())

    # --- Skills ---------------------------------------------------------------
    soft_skills = profile.skills.filter(category__kind="soft").select_related("category")
    technical_skills = profile.skills.filter(category__kind="technical").select_related("category")

    for title, qs in ((_("Soft Skills"), soft_skills), (_("Technical Skills"), technical_skills)):
        if not qs.exists():
            continue
        _section(lines, title)
        current_category = None
        for skill in qs.order_by("category__name", "-level", "name"):
            if skill.category_id != (current_category.id if current_category else None):
                current_category = skill.category
                lines.append("")
                lines.append(f"### {current_category.name}")
            lines.append(f"- **{skill.name}** — {skill.get_level_display()}")

    # --- Languages --------------------------------------------------------------
    user_languages = profile.languages.select_related("language").order_by("language__name")
    if user_languages.exists():
        _section(lines, _("Languages"))
        lines.append("")
        for ul in user_languages:
            lines.append(f"- **{ul.language.name}** — {ul.get_proficiency_display()}")

    # --- Work experience ----------------------------------------------------
    experiences = profile.experiences.order_by("-is_current", "-start_date")
    if experiences.exists():
        _section(lines, _("Work Experience"))
        for exp in experiences.prefetch_related("highlights"):
            lines.append("")
            lines.append(f"### {exp.job_title} — {exp.company}")
            meta_bits = [exp.duration_label]
            if exp.location:
                meta_bits.append(exp.location)
            if exp.employment_type:
                meta_bits.append(exp.get_employment_type_display())
            lines.append(f"*{' · '.join(meta_bits)}*")
            for highlight in exp.highlights.all():
                lines.append(f"- {highlight.text}")

    # --- Education: degrees --------------------------------------------------
    degrees = profile.degrees.order_by("-is_current", "-end_date", "-start_date")
    if degrees.exists():
        _section(lines, _("Education"))
        for degree in degrees:
            lines.append("")
            lines.append(f"### {degree.degree} — {degree.school}")
            meta_bits = []
            if degree.field_of_study:
                meta_bits.append(degree.field_of_study)
            start = _format_date(degree.start_date)
            end = _("Present") if degree.is_current else _format_date(degree.end_date)
            if start or end:
                meta_bits.append(f"{start} – {end}".strip(" –"))
            if degree.grade:
                meta_bits.append(f"{_('Grade')}: {degree.grade}")
            if meta_bits:
                lines.append(f"*{' · '.join(meta_bits)}*")
            if degree.description:
                lines.append("")
                lines.append(degree.description.strip())

    # --- Certificates ---------------------------------------------------------
    certificates = profile.certificates.order_by("-issue_date")
    if certificates.exists():
        _section(lines, _("Certificates"))
        for cert in certificates:
            lines.append("")
            lines.append(f"### {cert.name}")
            meta_bits = [cert.issuing_organization]
            if cert.issue_date:
                meta_bits.append(_("Issued %(date)s") % {"date": _format_date(cert.issue_date)})
            if cert.does_not_expire:
                meta_bits.append(_("No expiration"))
            elif cert.expiry_date:
                meta_bits.append(_("Expires %(date)s") % {"date": _format_date(cert.expiry_date)})
            lines.append(f"*{' · '.join(meta_bits)}*")
            if cert.credential_id:
                lines.append("")
                lines.append(f"{_('Credential ID')}: {cert.credential_id}")
            if cert.credential_url:
                lines.append(f"[{_('View credential')}]({cert.credential_url})")

    lines.append("")
    lines.append("---")
    generated_on = _("Generated with Easy Apply on %(date)s.") % {
        "date": date_format(timezone.localdate(), "DATE_FORMAT")
    }
    lines.append(f"_{generated_on}_")

    return "\n".join(lines) + "\n"


def recap_filename(profile) -> str:
    user = profile.user
    bits = [user.get_full_name() or user.email.split("@")[0], profile.name]
    slug = "-".join(" ".join(bits).strip().lower().split()) or "recap"
    return f"{slug}-easy-apply-recap.md"


def build_profile_snapshot(profile) -> dict:
    """Gather everything recorded in one profile into plain structured data —
    used to hand the AI a candidate's profile (e.g. to match it against a
    job's requirements) without formatting it as Markdown."""

    snapshot = {
        "headline": profile.headline,
        "bio": profile.bio,
        "soft_skills": [
            {"name": s.name, "category": s.category.name, "level": s.get_level_display()}
            for s in profile.skills.filter(category__kind="soft").select_related("category")
        ],
        "technical_skills": [
            {"name": s.name, "category": s.category.name, "level": s.get_level_display()}
            for s in profile.skills.filter(category__kind="technical").select_related("category")
        ],
        "languages": [
            {"name": ul.language.name, "proficiency": ul.get_proficiency_display()}
            for ul in profile.languages.select_related("language")
        ],
        "experience": [
            {
                "job_title": exp.job_title,
                "company": exp.company,
                "duration": exp.duration_label,
                "employment_type": exp.get_employment_type_display() if exp.employment_type else "",
                "highlights": [h.text for h in exp.highlights.all()],
            }
            for exp in profile.experiences.prefetch_related("highlights")
        ],
        "degrees": [
            {
                "degree": degree.degree,
                "school": degree.school,
                "field_of_study": degree.field_of_study,
            }
            for degree in profile.degrees.all()
        ],
        "certificates": [
            {"name": cert.name, "issuing_organization": cert.issuing_organization}
            for cert in profile.certificates.all()
        ],
    }
    return snapshot


def profile_snapshot_is_empty(snapshot: dict) -> bool:
    return not (
        snapshot.get("headline")
        or snapshot.get("bio")
        or snapshot.get("soft_skills")
        or snapshot.get("technical_skills")
        or snapshot.get("languages")
        or snapshot.get("experience")
        or snapshot.get("degrees")
        or snapshot.get("certificates")
    )


def build_resume_snapshot(profile) -> dict:
    """Everything `build_profile_snapshot` gathers, plus the contact
    details, locations and dates a resume needs — used when the AI has to
    draft a full document rather than just judge requirement coverage."""

    user = profile.user
    snapshot = build_profile_snapshot(profile)

    snapshot["contact"] = {
        "full_name": user.get_full_name(),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone": profile.phone,
        "location": profile.location,
        "linkedin_url": profile.linkedin_url,
        "portfolio_url": profile.portfolio_url,
        "github_url": profile.github_url,
    }
    snapshot["experience"] = [
        {
            "job_title": exp.job_title,
            "company": exp.company,
            "location": exp.location,
            "employment_type": exp.get_employment_type_display() if exp.employment_type else "",
            "duration": exp.duration_label,
            "is_current": exp.is_current,
            "highlights": [h.text for h in exp.highlights.all()],
        }
        for exp in profile.experiences.prefetch_related("highlights").order_by(
            "-is_current", "-start_date"
        )
    ]
    snapshot["degrees"] = [
        {
            "degree": degree.degree,
            "school": degree.school,
            "field_of_study": degree.field_of_study,
            "dates": _date_range(degree.start_date, degree.end_date, degree.is_current),
            "grade": degree.grade,
            "description": degree.description,
        }
        for degree in profile.degrees.all()
    ]
    snapshot["certificates"] = [
        {
            "name": cert.name,
            "issuing_organization": cert.issuing_organization,
            "issue_date": _format_date(cert.issue_date),
            "credential_id": cert.credential_id,
            "credential_url": cert.credential_url,
        }
        for cert in profile.certificates.all()
    ]
    return snapshot


def _date_range(start, end, is_current=False) -> str:
    start_label = _format_date(start)
    end_label = _("Present") if is_current else _format_date(end)
    if start_label and end_label:
        return f"{start_label} – {end_label}"
    return start_label or end_label


# ---------------------------------------------------------------------------
# Scoped profile slices
#
# The AI optimization in the refactor spec §6.1: a section's match call is sent
# ONLY the part of the profile it maps to. `build_profile_snapshot` above stays
# for the tailored-resume path, which legitimately needs everything.
# ---------------------------------------------------------------------------

def _preferences_for(profile):
    from preferences.models import JobPreference

    return JobPreference.objects.filter(profile=profile).prefetch_related("benefits").first()


def _slice_preferences_location(profile) -> dict:
    preference = _preferences_for(profile)
    if preference is None:
        return {}
    return {
        "preferred_locations": preference.preferred_locations_list,
        "acceptable_work_arrangements": preference.arrangements_list,
        "max_onsite_days_per_week": preference.max_onsite_days_per_week,
        "willing_to_relocate": preference.willing_to_relocate,
        "max_travel_percentage": preference.max_travel_percentage,
        "timezone_preference": preference.timezone_preference,
        "employment_types": preference.employment_types,
        "availability_notes": preference.availability_notes,
    }


def _slice_preferences_compensation(profile) -> dict:
    preference = _preferences_for(profile)
    if preference is None:
        return {}
    from preferences.models import BenefitPreference

    return {
        "desired_salary_min": preference.desired_salary_min,
        "desired_salary_max": preference.desired_salary_max,
        "salary_currency": preference.salary_currency,
        "salary_period": preference.salary_period,
        "benefits_wanted": [
            {"name": b.name, "importance": b.get_importance_display(), "notes": b.notes}
            for b in preference.benefits.all()
            if b.importance != BenefitPreference.NOT_IMPORTANT
        ],
    }


def _slice_experience(profile) -> dict:
    return {
        "experience": [
            {
                "job_title": exp.job_title,
                "company": exp.company,
                "duration": exp.duration_label,
                "employment_type": exp.get_employment_type_display() if exp.employment_type else "",
                "highlights": [h.text for h in exp.highlights.all()],
            }
            for exp in profile.experiences.prefetch_related("highlights")
        ]
    }


def _slice_technical_skills(profile) -> dict:
    return {
        "technical_skills": [
            {"name": s.name, "category": s.category.name, "level": s.get_level_display()}
            for s in profile.skills.filter(category__kind="technical").select_related("category")
        ]
    }


def _slice_soft_skills(profile) -> dict:
    return {
        "soft_skills": [
            {"name": s.name, "category": s.category.name, "level": s.get_level_display()}
            for s in profile.skills.filter(category__kind="soft").select_related("category")
        ]
    }


def _slice_languages(profile) -> dict:
    return {
        "languages": [
            {"name": ul.language.name, "proficiency": ul.get_proficiency_display()}
            for ul in profile.languages.select_related("language")
        ]
    }


def _slice_education(profile) -> dict:
    return {
        "degrees": [
            {
                "degree": d.degree,
                "school": d.school,
                "field_of_study": d.field_of_study,
                "dates": _date_range(d.start_date, d.end_date, d.is_current),
            }
            for d in profile.degrees.all()
        ],
        "certificates": [
            {
                "name": c.name,
                "issuing_organization": c.issuing_organization,
                "issue_date": _format_date(c.issue_date),
            }
            for c in profile.certificates.all()
        ],
    }


#: slice key -> builder. Keys come from jobs/sections.py.
SLICE_BUILDERS = {
    "preferences_location": _slice_preferences_location,
    "preferences_compensation": _slice_preferences_compensation,
    "experience": _slice_experience,
    "technical_skills": _slice_technical_skills,
    "soft_skills": _slice_soft_skills,
    "languages": _slice_languages,
    "education": _slice_education,
}


def build_profile_slice(profile, section_key: str) -> dict:
    """Return ONLY the part of `profile` that `section_key` maps to.

    Returns {} for a section that is never matched, and for a matched section
    whose slice is empty — callers use `profile_slice_is_empty` to skip the AI
    call entirely in that case (spec §6.2).

    Built under the profile's language, because the slice carries display
    strings ("Advanced", "Native / bilingual", "Jan 2020 – Present") straight
    into the prompt.
    """
    from jobs.sections import get_section

    section = get_section(section_key)
    if section is None or not section.profile_slices:
        return {}

    slice_data: dict = {}
    with use_language(profile.language):
        for slice_key in section.profile_slices:
            builder = SLICE_BUILDERS.get(slice_key)
            if builder:
                slice_data.update(builder(profile))
    return slice_data


def profile_slice_is_empty(slice_data: dict) -> bool:
    """True when there is nothing in the slice worth asking the AI about."""
    if not slice_data:
        return True
    for value in slice_data.values():
        if isinstance(value, (list, tuple, dict)):
            if value:
                return False
        elif isinstance(value, str):
            if value.strip():
                return False
        elif value not in (None, False):
            return False
    return True


def empty_slice_hint(section_key: str) -> str:
    """The evidence line written onto every element of a section whose profile
    slice is empty, instead of calling the AI."""
    from django.utils.translation import gettext as _

    hints = {
        "location_arrangement": _("No location or work-arrangement preferences recorded yet."),
        "compensation_benefits": _("No salary or benefit preferences recorded yet."),
        "responsibilities": _("No work experience or technical skills recorded yet."),
        "required_technical_skills": _("No technical skills recorded in your profile yet."),
        "desirable_technical_skills": _("No technical skills recorded in your profile yet."),
        "desirable_soft_skills": _("No soft skills recorded in your profile yet."),
        "languages": _("No languages recorded in your profile yet."),
        "education_certifications": _("No degrees or certificates recorded in your profile yet."),
    }
    return hints.get(section_key, _("Nothing in your profile covers this yet."))
