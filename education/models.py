from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Degree(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="degrees"
    )
    school = models.CharField(max_length=150)
    degree = models.CharField(max_length=150, help_text="e.g. Bachelor's, Master's, PhD")
    field_of_study = models.CharField(max_length=150, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    grade = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ["-is_current", "-end_date", "-start_date"]

    def __str__(self):
        return f"{self.degree} — {self.school}"

    def clean(self):
        if self.is_current:
            self.end_date = None
        elif self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date can't be before the start date."})


class Certificate(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="certificates"
    )
    name = models.CharField(max_length=150)
    issuing_organization = models.CharField(max_length=150)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    does_not_expire = models.BooleanField(default=False)
    credential_id = models.CharField(max_length=100, blank=True)
    credential_url = models.URLField(blank=True)

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self):
        return f"{self.name} — {self.issuing_organization}"

    def clean(self):
        if self.does_not_expire:
            self.expiry_date = None

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        from django.utils import timezone

        return self.expiry_date < timezone.localdate()
