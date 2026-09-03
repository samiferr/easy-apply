from django.conf import settings
from django.db import models
from django.urls import reverse


class JobPost(models.Model):
    """The parent record: one row per job posting a user has analyzed.

    Holds every "global" attribute pulled from the posting — everything
    that isn't an individual, line-by-line requirement (those live on
    Requirement, grouped under RequirementCategory below).
    """

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Analyzing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNCLEAR = "unclear"
    WORK_ARRANGEMENT_CHOICES = [
        (REMOTE, "Remote"),
        (HYBRID, "Hybrid"),
        (ONSITE, "On-site"),
        (UNCLEAR, "Not specified"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_posts"
    )
    source_url = models.URLField(max_length=1000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)

    # 1. Job title + summary
    title = models.CharField(max_length=200, blank=True)
    seniority_level = models.CharField(max_length=100, blank=True)
    summary = models.TextField(blank=True)

    # 5. Location, work arrangement & travel
    location = models.CharField(max_length=200, blank=True)
    work_arrangement = models.CharField(
        max_length=20, choices=WORK_ARRANGEMENT_CHOICES, blank=True
    )
    timezone_expectations = models.CharField(max_length=200, blank=True)
    relocation_offered = models.BooleanField(null=True, blank=True)
    travel_percentage = models.CharField(max_length=100, blank=True)

    # 6. Compensation & benefits
    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    salary_currency = models.CharField(max_length=10, blank=True)
    salary_period = models.CharField(max_length=20, blank=True, help_text="e.g. year, hour")
    compensation_notes = models.TextField(blank=True)
    benefits = models.TextField(blank=True, help_text="One benefit per line.")

    # 7. Company / team information
    company_name = models.CharField(max_length=200, blank=True)
    company_size = models.CharField(max_length=100, blank=True)
    company_stage = models.CharField(max_length=100, blank=True)
    company_industry = models.CharField(max_length=150, blank=True)
    company_mission = models.TextField(blank=True)
    reports_to = models.CharField(max_length=150, blank=True)

    # 8. Application instructions & deadline
    application_instructions = models.TextField(blank=True)
    application_deadline = models.CharField(max_length=100, blank=True)

    # Bonus: red flags / growth language / values alignment
    red_flags = models.TextField(blank=True, help_text="One red flag per line.")
    growth_language_notes = models.TextField(blank=True)
    diversity_statement = models.TextField(blank=True)

    # Bookkeeping
    raw_text = models.TextField(blank=True)
    manual_text = models.TextField(
        blank=True, help_text="Job description pasted by hand instead of fetched from the URL."
    )
    ai_model = models.CharField(max_length=100, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.source_url

    def get_absolute_url(self):
        return reverse("jobs:detail", args=[self.pk])

    @property
    def benefits_list(self):
        return [line.strip() for line in self.benefits.splitlines() if line.strip()]

    @property
    def red_flags_list(self):
        return [line.strip() for line in self.red_flags.splitlines() if line.strip()]

    @property
    def salary_range_display(self):
        if not self.salary_min and not self.salary_max:
            return ""
        currency = self.salary_currency or ""
        period = f"/{self.salary_period}" if self.salary_period else ""
        if self.salary_min and self.salary_max and self.salary_min != self.salary_max:
            return f"{currency}{self.salary_min:,} – {currency}{self.salary_max:,}{period}"
        amount = self.salary_max or self.salary_min
        return f"{currency}{amount:,}{period}"


class RequirementCategory(models.Model):
    """A named group of requirements within a job post (e.g. "Required
    Qualifications", "Responsibilities", "Preferred Qualifications")."""

    RESPONSIBILITIES = "responsibilities"
    REQUIRED = "required"
    PREFERRED = "preferred"
    OTHER = "other"
    TYPE_CHOICES = [
        (RESPONSIBILITIES, "Responsibilities"),
        (REQUIRED, "Required qualifications"),
        (PREFERRED, "Preferred qualifications"),
        (OTHER, "Other"),
    ]

    job = models.ForeignKey(JobPost, on_delete=models.CASCADE, related_name="categories")
    category_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=OTHER)
    name = models.CharField(max_length=150)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name_plural = "requirement categories"

    def __str__(self):
        return f"{self.name} ({self.job})"


class Requirement(models.Model):
    """A single, atomic requirement / responsibility line within a category."""

    category = models.ForeignKey(
        RequirementCategory, on_delete=models.CASCADE, related_name="requirements"
    )
    text = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text[:80]
