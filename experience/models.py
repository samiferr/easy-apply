from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class WorkExperience(models.Model):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    FREELANCE = "freelance"
    INTERNSHIP = "internship"
    EMPLOYMENT_TYPE_CHOICES = [
        (FULL_TIME, "Full-time"),
        (PART_TIME, "Part-time"),
        (CONTRACT, "Contract"),
        (FREELANCE, "Freelance"),
        (INTERNSHIP, "Internship"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="experiences"
    )
    job_title = models.CharField(max_length=150)
    company = models.CharField(max_length=150)
    location = models.CharField(max_length=120, blank=True)
    employment_type = models.CharField(
        max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, blank=True
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_current", "-start_date"]

    def __str__(self):
        return f"{self.job_title} at {self.company}"

    def clean(self):
        if self.is_current:
            self.end_date = None
        elif self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date can't be before the start date."})

    @property
    def duration_label(self):
        end = "Present" if self.is_current else (self.end_date.strftime("%b %Y") if self.end_date else "—")
        return f"{self.start_date.strftime('%b %Y')} – {end}"


class ExperienceHighlight(models.Model):
    """A single bullet point describing an achievement/responsibility
    within a WorkExperience — recorded as its own row instead of being
    part of one free-text description."""

    experience = models.ForeignKey(
        WorkExperience, on_delete=models.CASCADE, related_name="highlights"
    )
    text = models.CharField(max_length=500)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text[:80]
