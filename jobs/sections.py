"""The closed set of job-analysis sections.

This module is the single source of truth for:

* which sections a job analysis may contain (the AI may never invent others),
* the order they appear in the tab rail,
* which sections carry evaluable element rows vs. plain prose,
* which slice of the candidate's profile each matched section is compared
  against (the AI optimization in the refactor spec §6.1), and
* which profile object the "Add to my profile" button creates (§4).

Adding a section later means one entry in SECTIONS — not a chain of `if`
branches spread across services, views and templates.
"""

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

# --- Profile slice keys -----------------------------------------------------
# These name the parts of the candidate profile that can be sent to the AI.
# `core.utils.build_profile_slice` maps each one to real data.
SLICE_PREFERENCES_LOCATION = "preferences_location"
SLICE_PREFERENCES_COMPENSATION = "preferences_compensation"
SLICE_EXPERIENCE = "experience"
SLICE_TECHNICAL_SKILLS = "technical_skills"
SLICE_SOFT_SKILLS = "soft_skills"
SLICE_LANGUAGES = "languages"
SLICE_EDUCATION = "education"


@dataclass(frozen=True)
class Section:
    key: str
    label: object                 # lazy translated string
    has_elements: bool            # renders a match table vs. plain prose
    profile_slices: tuple = ()    # empty => never matched
    add_target: str = ""          # registry key in jobs/profile_targets.py
    icon: str = ""                # heroicon-ish name used by the tab rail
    description: object = ""

    @property
    def is_matched(self) -> bool:
        return bool(self.profile_slices)


SECTIONS: tuple[Section, ...] = (
    Section(
        key="overview",
        label=_("Overview"),
        has_elements=False,
        icon="document",
        description=_("What the role is, in the posting's own words."),
    ),
    Section(
        key="company",
        label=_("Company"),
        has_elements=False,
        icon="building",
        description=_("Size, stage, industry, mission and who the role reports to."),
    ),
    Section(
        key="location_arrangement",
        label=_("Location & work arrangement"),
        has_elements=True,
        profile_slices=(SLICE_PREFERENCES_LOCATION,),
        add_target="job_preference_location",
        icon="map-pin",
        description=_("Checked against your job preferences."),
    ),
    Section(
        key="compensation_benefits",
        label=_("Compensation & benefits"),
        has_elements=True,
        profile_slices=(SLICE_PREFERENCES_COMPENSATION,),
        add_target="benefit_preference",
        icon="currency",
        description=_("Checked against your job preferences."),
    ),
    Section(
        key="how_to_apply",
        label=_("How to Apply"),
        has_elements=False,
        icon="paper-plane",
        description=_("Application instructions and any deadline."),
    ),
    Section(
        key="responsibilities",
        label=_("Responsibilities"),
        has_elements=True,
        profile_slices=(SLICE_EXPERIENCE, SLICE_TECHNICAL_SKILLS),
        add_target="experience_highlight",
        icon="list-checks",
        description=_("Checked against your experience and technical skills."),
    ),
    Section(
        key="required_technical_skills",
        label=_("Required Technical Skills"),
        has_elements=True,
        profile_slices=(SLICE_TECHNICAL_SKILLS,),
        add_target="technical_skill",
        icon="code",
        description=_("Checked against your technical skills."),
    ),
    Section(
        key="desirable_technical_skills",
        label=_("Desirable Technical Skills"),
        has_elements=True,
        profile_slices=(SLICE_TECHNICAL_SKILLS,),
        add_target="technical_skill",
        icon="code",
        description=_("Checked against your technical skills."),
    ),
    Section(
        key="desirable_soft_skills",
        label=_("Desirable Soft Skills"),
        has_elements=True,
        profile_slices=(SLICE_SOFT_SKILLS,),
        add_target="soft_skill",
        icon="heart",
        description=_("Checked against your soft skills."),
    ),
    Section(
        key="languages",
        label=_("Languages"),
        has_elements=True,
        profile_slices=(SLICE_LANGUAGES,),
        add_target="language",
        icon="globe",
        description=_("Checked against the languages on your profile."),
    ),
    Section(
        key="education_certifications",
        label=_("Education & Certifications"),
        has_elements=True,
        profile_slices=(SLICE_EDUCATION,),
        add_target="education",
        icon="academic-cap",
        description=_("Checked against your degrees and certificates."),
    ),
    Section(
        key="worth_noting",
        label=_("Worth noting"),
        has_elements=False,
        icon="sparkles",
        description=_("Growth, mentorship, impact and inclusion signals."),
    ),
    Section(
        key="red_flags",
        label=_("Possible red flags"),
        has_elements=False,
        icon="warning",
        description=_("Things worth a second look before you apply."),
    ),
)

SECTION_MAP: dict[str, Section] = {s.key: s for s in SECTIONS}
SECTION_KEYS: tuple[str, ...] = tuple(s.key for s in SECTIONS)
SECTION_CHOICES = [(s.key, s.label) for s in SECTIONS]
SECTION_ORDER: dict[str, int] = {s.key: i for i, s in enumerate(SECTIONS)}

#: Sections that carry evaluable rows and are compared to the profile.
MATCHED_SECTION_KEYS: tuple[str, ...] = tuple(
    s.key for s in SECTIONS if s.is_matched and s.has_elements
)
#: Sections that carry rows at all (currently identical to the above, but kept
#: separate so a future unmatched-but-listed section doesn't break the matcher).
ELEMENT_SECTION_KEYS: tuple[str, ...] = tuple(s.key for s in SECTIONS if s.has_elements)


def get_section(key: str) -> Section | None:
    return SECTION_MAP.get(key)


def is_valid_key(key) -> bool:
    return isinstance(key, str) and key in SECTION_MAP


def order_for(key: str) -> int:
    return SECTION_ORDER.get(key, len(SECTIONS))


def label_for(key: str):
    section = SECTION_MAP.get(key)
    return section.label if section else key
