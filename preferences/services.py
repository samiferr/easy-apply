"""Use cases of a profile's job preferences and its benefit list.

`JobPreference` is what the candidate is looking for in a role; it is the
profile-side counterpart of a job post's "Location & work arrangement" and
"Compensation & benefits" sections, which are matched against it.

Use cases: docs/use-cases/UC03_PROFILE_DATA_MANAGEMENT.md (UC-03.6).
"""

from django.utils.translation import gettext_lazy as _

from .models import BenefitPreference, JobPreference

#: Seeded the first time a user opens the Job preferences tab, so it is never empty.
SEED_BENEFITS = [
    _("Health benefits"),
    _("Dental care"),
    _("Vision care"),
    _("Life insurance"),
    _("Retirement / pension matching"),
    _("Paid time off"),
    _("Parental leave"),
    _("Professional development budget"),
    _("Flexible hours"),
    _("Equity / stock options"),
    _("Remote work stipend"),
    _("Wellness / gym"),
]


# UC-03.6 — Career Preferences, Work Arrangements & Benefits Prioritization (step 2)
def get_or_create_preference(profile) -> JobPreference:
    """Return the profile's JobPreference, seeding the starter benefit list the
    first time it is created."""
    preference, created = JobPreference.objects.get_or_create(profile=profile)
    if created:
        BenefitPreference.objects.bulk_create(
            BenefitPreference(
                preference=preference,
                name=str(name),
                importance=BenefitPreference.NICE_TO_HAVE,
            )
            for name in SEED_BENEFITS
        )
    return preference


# UC-03.6 — step 1: the scalar preferences and the benefit rows shown together
def preference_screen(profile) -> dict:
    preference = get_or_create_preference(profile)
    return {"preference": preference, "benefits": preference.benefits.all()}


# UC-03.6 — steps 3 and 5: compensation, location and arrangement are saved as a whole
def save_preferences(form) -> JobPreference:
    return form.save()


# UC-03.6 — the workspace boundary: a benefit is reached through its profile's preference
def profile_benefits(profile):
    return BenefitPreference.objects.filter(preference__profile=profile)


# UC-03.6 — step 4: a custom benefit joins the list
def add_benefit(preference: JobPreference, form) -> BenefitPreference:
    benefit = form.save(commit=False)
    benefit.preference = preference
    benefit.save()
    return benefit


# UC-03.6 — step 4: the inline importance dropdown. An unknown value is ignored.
def change_benefit_importance(benefit: BenefitPreference, importance) -> bool:
    """Set how much the benefit matters. Returns whether it changed anything."""
    valid = {choice[0] for choice in BenefitPreference.IMPORTANCE_CHOICES}
    if importance not in valid:
        return False
    benefit.importance = importance
    benefit.save(update_fields=["importance"])
    return True


# UC-03.6 — removing a benefit from the list
def remove_benefit(benefit: BenefitPreference) -> None:
    benefit.delete()
