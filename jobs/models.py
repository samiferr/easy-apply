from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .sections import MATCHED_SECTION_KEYS, SECTION_CHOICES, SECTION_ORDER


class JobPost(models.Model):
    """The parent record: one row per job posting a user has analyzed.

    Holds every "global" attribute pulled from the posting. The line-by-line
    detail lives on JobElement, grouped under the fixed JobSection rows below —
    see jobs/sections.py for the closed section list.
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
        (REMOTE, _("Remote")),
        (HYBRID, _("Hybrid")),
        (ONSITE, _("On-site")),
        (UNCLEAR, _("Not specified")),
    ]

    profile = models.ForeignKey(
        "accounts.Profile", on_delete=models.CASCADE, related_name="job_posts"
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
    analysis_language = models.CharField(
        max_length=10,
        blank=True,
        help_text=(
            "The language this stored analysis is written in. Copied from the "
            "profile at analysis time, so the record says what it is even if the "
            "job is later read from somewhere else."
        ),
    )
    raw_text = models.TextField(blank=True)
    manual_text = models.TextField(
        blank=True, help_text="Job description pasted by hand instead of fetched from the URL."
    )
    ai_model = models.CharField(max_length=100, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)
    profile_matched_at = models.DateTimeField(null=True, blank=True)
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

    def element_match_summary(self):
        """Aggregate match status across every element in a *matched* section.

        Rows in prose-only sections (Overview, Company, ...) are never counted —
        they carry no verdict.
        """
        elements = JobElement.objects.filter(
            section__job=self, section__key__in=MATCHED_SECTION_KEYS
        )
        total = elements.count()
        strong = elements.filter(match_status=JobElement.STRONG).count()
        partial = elements.filter(match_status=JobElement.PARTIAL).count()
        none_ = elements.filter(match_status=JobElement.NONE).count()
        analyzed = strong + partial + none_
        score_percent = round(((strong + 0.5 * partial) / total) * 100) if total else 0
        return {
            "total": total,
            "strong": strong,
            "partial": partial,
            "none": none_,
            "analyzed": analyzed,
            "unanalyzed": total - analyzed,
            "score_percent": score_percent,
        }

    @property
    def needs_reanalysis(self) -> bool:
        """True for jobs imported before the fixed-section refactor — their
        categories were wiped by the 0002 data migration."""
        return self.status == self.STATUS_COMPLETED and not self.sections.exists()


class JobSection(models.Model):
    """One of the fixed sections of a job analysis (see jobs/sections.py).

    The set of keys is closed: the AI may not invent sections, and the importer
    discards anything it does not recognise.
    """

    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    MATCH_STATE_CHOICES = [
        (IDLE, _("Not matched yet")),
        (RUNNING, _("Matching…")),
        (DONE, _("Matched")),
        (FAILED, _("Matching failed")),
    ]

    job = models.ForeignKey(JobPost, on_delete=models.CASCADE, related_name="sections")
    key = models.CharField(max_length=40, choices=SECTION_CHOICES)
    order = models.PositiveSmallIntegerField(default=0)
    body = models.TextField(blank=True, help_text="Prose, for sections without element rows.")
    match_state = models.CharField(max_length=20, choices=MATCH_STATE_CHOICES, default=IDLE)
    match_error = models.TextField(blank=True)
    matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("job section")
        verbose_name_plural = _("job sections")
        constraints = [
            models.UniqueConstraint(fields=["job", "key"], name="unique_section_per_job")
        ]

    def __str__(self):
        return f"{self.key} ({self.job_id})"

    def save(self, *args, **kwargs):
        if not self.order:
            self.order = SECTION_ORDER.get(self.key, 0)
        super().save(*args, **kwargs)

    @property
    def spec(self):
        """The Section dataclass from jobs/sections.py describing this row."""
        from .sections import get_section

        return get_section(self.key)

    @property
    def label(self):
        spec = self.spec
        return spec.label if spec else self.key

    @property
    def is_matched_section(self) -> bool:
        return self.key in MATCHED_SECTION_KEYS

    def match_summary(self):
        elements = self.elements.all()
        total = len(elements)
        strong = sum(1 for e in elements if e.match_status == JobElement.STRONG)
        partial = sum(1 for e in elements if e.match_status == JobElement.PARTIAL)
        none_ = sum(1 for e in elements if e.match_status == JobElement.NONE)
        return {
            "total": total,
            "strong": strong,
            "partial": partial,
            "none": none_,
            "analyzed": strong + partial + none_,
            "score_percent": round(((strong + 0.5 * partial) / total) * 100) if total else 0,
        }


class JobElement(models.Model):
    """A single, atomic line within a section — a responsibility, a required
    skill, a benefit, a language requirement."""

    STRONG = "strong"
    PARTIAL = "partial"
    NONE = "none"
    MATCH_CHOICES = [
        (STRONG, _("Strong match")),
        (PARTIAL, _("Partial match")),
        (NONE, _("Not covered")),
    ]

    section = models.ForeignKey(
        JobSection, on_delete=models.CASCADE, related_name="elements"
    )
    text = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    match_status = models.CharField(max_length=10, choices=MATCH_CHOICES, blank=True)
    match_evidence = models.TextField(blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    is_evaluating = models.BooleanField(
        default=False, help_text="True while a single-element re-evaluation is in flight."
    )
    added_to_profile_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("job element")
        verbose_name_plural = _("job elements")

    def __str__(self):
        return self.text[:80]

    @property
    def is_matched(self) -> bool:
        return bool(self.match_status)

    @property
    def was_added_to_profile(self) -> bool:
        return self.added_to_profile_at is not None

    @property
    def badge_class(self) -> str:
        return {
            self.STRONG: "badge-strong",
            self.PARTIAL: "badge-partial",
            self.NONE: "badge-none",
        }.get(self.match_status, "badge-pending")
