from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models


def resume_upload_path(instance, filename):
    return f"resumes/user_{instance.user_id}/{filename}"


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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="resume_imports"
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
