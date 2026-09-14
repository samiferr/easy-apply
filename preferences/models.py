from django.db import models
from django.utils.translation import gettext_lazy as _


class JobPreference(models.Model):
    """What the candidate is looking for in a role.

    This is the profile-side counterpart of a job post's "Location & work
    arrangement" and "Compensation & benefits" sections — see
    `jobs/sections.py`, which maps both of those to this model.
    """

    SALARY_PERIOD_CHOICES = [
        ("year", _("Per year")),
        ("month", _("Per month")),
        ("day", _("Per day")),
        ("hour", _("Per hour")),
    ]

    profile = models.OneToOneField(
        "accounts.Profile", on_delete=models.CASCADE, related_name="job_preference"
    )

    # --- Compensation ----------------------------------------------------
    desired_salary_min = models.PositiveIntegerField(
        _("Minimum salary"), null=True, blank=True
    )
    desired_salary_max = models.PositiveIntegerField(
        _("Target salary"), null=True, blank=True
    )
    salary_currency = models.CharField(_("Currency"), max_length=10, blank=True)
    salary_period = models.CharField(
        _("Period"), max_length=20, choices=SALARY_PERIOD_CHOICES, default="year", blank=True
    )

    # --- Location & work arrangement -------------------------------------
    preferred_locations = models.TextField(
        _("Preferred locations"), blank=True, help_text=_("One location per line.")
    )
    remote_ok = models.BooleanField(_("Open to remote"), default=False)
    hybrid_ok = models.BooleanField(_("Open to hybrid"), default=False)
    onsite_ok = models.BooleanField(_("Open to on-site"), default=False)
    max_onsite_days_per_week = models.PositiveSmallIntegerField(
        _("Max. on-site days / week"), null=True, blank=True
    )
    willing_to_relocate = models.BooleanField(
        _("Willing to relocate"), null=True, blank=True
    )
    max_travel_percentage = models.PositiveSmallIntegerField(
        _("Max. travel (%)"), null=True, blank=True
    )
    timezone_preference = models.CharField(
        _("Time zone"), max_length=120, blank=True,
        help_text=_("e.g. “EST ±2h” or “Europe only”"),
    )
    employment_types = models.CharField(
        _("Employment types"), max_length=200, blank=True,
        help_text=_("Comma-separated, e.g. “Full-time, Contract”."),
    )
    availability_notes = models.TextField(_("Availability"), blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("job preference")
        verbose_name_plural = _("job preferences")

    def __str__(self):
        return f"Job preferences of {self.profile}"

    @property
    def preferred_locations_list(self):
        return [line.strip() for line in self.preferred_locations.splitlines() if line.strip()]

    @property
    def arrangements_list(self):
        out = []
        if self.remote_ok:
            out.append("remote")
        if self.hybrid_ok:
            out.append("hybrid")
        if self.onsite_ok:
            out.append("onsite")
        return out

    @property
    def salary_range_display(self):
        if not self.desired_salary_min and not self.desired_salary_max:
            return ""
        currency = self.salary_currency or ""
        period = f"/{self.salary_period}" if self.salary_period else ""
        if self.desired_salary_min and self.desired_salary_max:
            return f"{currency}{self.desired_salary_min:,} – {currency}{self.desired_salary_max:,}{period}"
        amount = self.desired_salary_max or self.desired_salary_min
        return f"{currency}{amount:,}{period}"

    @property
    def is_empty(self) -> bool:
        return not (
            self.desired_salary_min
            or self.desired_salary_max
            or self.preferred_locations.strip()
            or self.remote_ok
            or self.hybrid_ok
            or self.onsite_ok
            or self.timezone_preference
            or self.employment_types
            or self.availability_notes.strip()
            or self.benefits.exclude(importance=BenefitPreference.NOT_IMPORTANT).exists()
        )


class BenefitPreference(models.Model):
    """One benefit the candidate cares about, and how much.

    Rows are created either from the seed list below or by the
    "Add to my profile" button on a job's Compensation & benefits section.
    """

    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"
    NOT_IMPORTANT = "not_important"
    IMPORTANCE_CHOICES = [
        (MUST_HAVE, _("Must have")),
        (NICE_TO_HAVE, _("Nice to have")),
        (NOT_IMPORTANT, _("Not important")),
    ]

    preference = models.ForeignKey(
        JobPreference, on_delete=models.CASCADE, related_name="benefits"
    )
    name = models.CharField(_("Benefit"), max_length=120)
    importance = models.CharField(
        _("Importance"), max_length=20, choices=IMPORTANCE_CHOICES, default=NICE_TO_HAVE
    )
    notes = models.CharField(_("Notes"), max_length=250, blank=True)

    class Meta:
        ordering = ["importance", "name"]
        verbose_name = _("benefit preference")
        verbose_name_plural = _("benefit preferences")
        constraints = [
            models.UniqueConstraint(
                fields=["preference", "name"], name="unique_benefit_per_preference"
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.get_importance_display()}"


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
