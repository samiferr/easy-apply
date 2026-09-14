from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


def resume_upload_path(instance, filename):
    return f"resumes/profile_{instance.profile_id}/{filename}"


class ResumeImport(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_APPLIED = "applied"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Analyzing"),
        (STATUS_COMPLETED, "Ready to review"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_FAILED, "Failed"),
    ]

    profile = models.ForeignKey(
        "accounts.Profile", on_delete=models.CASCADE, related_name="resume_imports"
    )
    file = models.FileField(
        upload_to=resume_upload_path,
        validators=[FileExtensionValidator(["pdf", "docx", "txt"])],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    raw_text = models.TextField(blank=True)
    ai_response = models.JSONField(null=True, blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_filename or f"Resume #{self.pk}"


class TailoredResume(models.Model):
    """A job-specific resume drafted by the AI from the user's profile and
    the job's requirement match, kept as editable Markdown until the user
    is happy with it and exports it as a PDF."""

    profile = models.ForeignKey(
        "accounts.Profile", on_delete=models.CASCADE, related_name="tailored_resumes"
    )
    job = models.OneToOneField(
        "jobs.JobPost", on_delete=models.CASCADE, related_name="tailored_resume"
    )
    # TailoredResume was the only AI path with no status of its own — added so
    # generation can be tracked like the other three (spec §7.2).
    STATE_PENDING = "pending"
    STATE_PROCESSING = "processing"
    STATE_COMPLETED = "completed"
    STATE_FAILED = "failed"
    STATE_CHOICES = [
        (STATE_PENDING, "Pending"),
        (STATE_PROCESSING, "Generating"),
        (STATE_COMPLETED, "Ready"),
        (STATE_FAILED, "Failed"),
    ]

    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_PENDING)
    error_message = models.TextField(blank=True)
    markdown = models.TextField(blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    edited_by_user = models.BooleanField(
        default=False, help_text="True once the user has changed the AI's draft."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Tailored resume for {self.job}"

    def get_absolute_url(self):
        return reverse("resume:tailored", args=[self.job_id])

    @property
    def is_ready(self) -> bool:
        return self.state == self.STATE_COMPLETED and bool(self.markdown)

    @property
    def pdf_filename(self) -> str:
        """A safe, descriptive download name, e.g. "jane-doe-acme-resume.pdf"."""
        user = self.profile.user
        bits = [user.get_full_name() or user.email.split("@")[0]]
        if self.job.company_name:
            bits.append(self.job.company_name)
        elif self.job.title:
            bits.append(self.job.title)
        slug = slugify(" ".join(bits)) or "resume"
        return f"{slug}-resume.pdf"

    @property
    def markdown_filename(self) -> str:
        return f"{self.pdf_filename.removesuffix('.pdf')}.md"
