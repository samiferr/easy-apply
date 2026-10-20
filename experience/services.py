"""Use cases of a profile's work history.

A `WorkExperience` owns its highlight bullets as separate rows — one
achievement each, re-orderable — rather than one free-text block.

Use cases: docs/use-cases/UC03_PROFILE_DATA_MANAGEMENT.md (UC-03.4).
"""

from .models import WorkExperience


# UC-03.4 — Professional Work Experience & Granular Highlights: the workspace boundary
def profile_experiences(profile):
    return WorkExperience.objects.filter(profile=profile)


# UC-03.4 — step 1 / step 8: the history, current role first, with its highlights
def list_experiences(profile):
    return profile_experiences(profile).prefetch_related("highlights")


# UC-03.4 — step 7: the role is saved against the profile, then its highlight rows
def save_experience(profile, form, formset) -> WorkExperience:
    """Save a validated `WorkExperienceForm` and its `HighlightFormSet`.

    (Model validation has already cleared `end_date` for a current role and
    refused an end before the start.)
    """
    experience = form.save(commit=False)
    experience.profile = profile
    experience.save()
    formset.instance = experience
    formset.save()
    return experience


# UC-03.4 — removing a role takes its highlights with it (cascade)
def remove_experience(experience: WorkExperience) -> None:
    experience.delete()
