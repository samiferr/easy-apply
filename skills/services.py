"""Use cases of a profile's soft and technical skills.

Soft and technical skills are two screens over one model, told apart by the
kind of their category. Every query is scoped to a profile: that is what keeps
one workspace's skills out of another's.

Use cases: docs/use-cases/UC03_PROFILE_DATA_MANAGEMENT.md (UC-03.1, UC-03.2).
"""

from itertools import groupby

from .models import SkillCategory, UserSkill

#: The two screens, one per sidebar entry.
KINDS = (SkillCategory.SOFT, SkillCategory.TECHNICAL)


# UC-03.1 / UC-03.2 — Technical / Soft Skills Management: which screens exist
def is_valid_kind(kind) -> bool:
    return kind in KINDS


# UC-03.1 / UC-03.2 — the workspace boundary: a profile only ever sees its own skills
def profile_skills(profile):
    return UserSkill.objects.filter(profile=profile)


# UC-03.1 — Technical Skills Management by Category Tabs (step 2) and UC-03.2
def skills_by_category(profile, kind: str) -> list:
    """`[(category, [skills])]` for one kind: what the category tabs are built from."""
    skills = profile_skills(profile).filter(category__kind=kind).select_related("category")
    return group_by_category(skills)


# UC-03.1 — step 2: relies on the queryset being ordered by category
def group_by_category(skills) -> list:
    grouped = []
    for category, items in groupby(skills, key=lambda skill: skill.category):
        grouped.append((category, list(items)))
    return grouped


# UC-03.1 — step 7 / UC-03.2 — step 4: the skill is recorded against the profile
def add_skill(profile, form) -> UserSkill:
    form.instance.profile = profile
    return form.save()


# UC-03.1 — alternative flow "Skill Editing / Deletion" (editing)
def update_skill(form) -> UserSkill:
    return form.save()


# UC-03.1 — alternative flow "Skill Editing / Deletion" (deleting)
def remove_skill(skill: UserSkill) -> None:
    skill.delete()
