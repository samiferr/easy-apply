"""Utilities to render a Markdown recap of everything a user has recorded."""

from django.utils import timezone


def _format_date(value, fmt="%B %Y"):
    return value.strftime(fmt) if value else ""


def _section(lines, title, level=2):
    lines.append("")
    lines.append(f"{'#' * level} {title}")


def generate_markdown_recap(user) -> str:
    """Build a single Markdown document summarizing a user's profile, skills,
    languages, work experience, degrees and certificates."""

    lines: list[str] = []

    full_name = user.get_full_name() or user.get_short_name()
    profile = getattr(user, "profile", None)

    lines.append(f"# {full_name}")
    if profile and profile.headline:
        lines.append(f"*{profile.headline}*")

    lines.append("")
    contact_bits = [f"- **Email:** {user.email}"]
    if profile:
        if profile.phone:
            contact_bits.append(f"- **Phone:** {profile.phone}")
        if profile.location:
            contact_bits.append(f"- **Location:** {profile.location}")
        if profile.linkedin_url:
            contact_bits.append(f"- **LinkedIn:** {profile.linkedin_url}")
        if profile.portfolio_url:
            contact_bits.append(f"- **Portfolio:** {profile.portfolio_url}")
        if profile.github_url:
            contact_bits.append(f"- **GitHub:** {profile.github_url}")
    lines.extend(contact_bits)

    if profile and profile.bio:
        _section(lines, "About")
        lines.append("")
        lines.append(profile.bio.strip())

    # --- Skills ---------------------------------------------------------------
    soft_skills = user.skills.filter(category__kind="soft").select_related("category")
    technical_skills = user.skills.filter(category__kind="technical").select_related("category")

    for title, qs in (("Soft Skills", soft_skills), ("Technical Skills", technical_skills)):
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
    user_languages = user.languages.select_related("language").order_by("language__name")
    if user_languages.exists():
        _section(lines, "Languages")
        lines.append("")
        for ul in user_languages:
            lines.append(f"- **{ul.language.name}** — {ul.get_proficiency_display()}")

    # --- Work experience ----------------------------------------------------
    experiences = user.experiences.order_by("-is_current", "-start_date")
    if experiences.exists():
        _section(lines, "Work Experience")
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
    degrees = user.degrees.order_by("-is_current", "-end_date", "-start_date")
    if degrees.exists():
        _section(lines, "Education")
        for degree in degrees:
            lines.append("")
            lines.append(f"### {degree.degree} — {degree.school}")
            meta_bits = []
            if degree.field_of_study:
                meta_bits.append(degree.field_of_study)
            start = _format_date(degree.start_date)
            end = "Present" if degree.is_current else _format_date(degree.end_date)
            if start or end:
                meta_bits.append(f"{start} – {end}".strip(" –"))
            if degree.grade:
                meta_bits.append(f"Grade: {degree.grade}")
            if meta_bits:
                lines.append(f"*{' · '.join(meta_bits)}*")
            if degree.description:
                lines.append("")
                lines.append(degree.description.strip())

    # --- Certificates ---------------------------------------------------------
    certificates = user.certificates.order_by("-issue_date")
    if certificates.exists():
        _section(lines, "Certificates")
        for cert in certificates:
            lines.append("")
            lines.append(f"### {cert.name}")
            meta_bits = [cert.issuing_organization]
            if cert.issue_date:
                meta_bits.append(f"Issued {_format_date(cert.issue_date)}")
            if cert.does_not_expire:
                meta_bits.append("No expiration")
            elif cert.expiry_date:
                meta_bits.append(f"Expires {_format_date(cert.expiry_date)}")
            lines.append(f"*{' · '.join(meta_bits)}*")
            if cert.credential_id:
                lines.append("")
                lines.append(f"Credential ID: {cert.credential_id}")
            if cert.credential_url:
                lines.append(f"[View credential]({cert.credential_url})")

    lines.append("")
    lines.append("---")
    lines.append(
        f"_Generated with Easy Apply on {timezone.localdate().strftime('%B %d, %Y')}._"
    )

    return "\n".join(lines) + "\n"


def recap_filename(user) -> str:
    slug = (user.get_full_name() or user.email.split("@")[0]).strip().lower()
    slug = "-".join(slug.split()) or "recap"
    return f"{slug}-easy-apply-recap.md"


def build_profile_snapshot(user) -> dict:
    """Gather everything a user has recorded into plain structured data —
    used to hand the AI a candidate's profile (e.g. to match it against a
    job's requirements) without formatting it as Markdown."""

    profile = getattr(user, "profile", None)

    snapshot = {
        "headline": profile.headline if profile else "",
        "bio": profile.bio if profile else "",
        "soft_skills": [
            {"name": s.name, "category": s.category.name, "level": s.get_level_display()}
            for s in user.skills.filter(category__kind="soft").select_related("category")
        ],
        "technical_skills": [
            {"name": s.name, "category": s.category.name, "level": s.get_level_display()}
            for s in user.skills.filter(category__kind="technical").select_related("category")
        ],
        "languages": [
            {"name": ul.language.name, "proficiency": ul.get_proficiency_display()}
            for ul in user.languages.select_related("language")
        ],
        "experience": [
            {
                "job_title": exp.job_title,
                "company": exp.company,
                "duration": exp.duration_label,
                "employment_type": exp.get_employment_type_display() if exp.employment_type else "",
                "highlights": [h.text for h in exp.highlights.all()],
            }
            for exp in user.experiences.prefetch_related("highlights")
        ],
        "degrees": [
            {
                "degree": degree.degree,
                "school": degree.school,
                "field_of_study": degree.field_of_study,
            }
            for degree in user.degrees.all()
        ],
        "certificates": [
            {"name": cert.name, "issuing_organization": cert.issuing_organization}
            for cert in user.certificates.all()
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
