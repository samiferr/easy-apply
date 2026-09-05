from django import forms
from django.conf import settings

from core.forms import StyledModelForm

from .models import ResumeImport


class ResumeUploadForm(StyledModelForm):
    class Meta:
        model = ResumeImport
        fields = ["file"]
        labels = {"file": "Resume file"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = (
            f"PDF, DOCX, or TXT — up to {settings.RESUME_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
        self.fields["file"].widget.attrs["accept"] = ".pdf,.docx,.txt"
        self.fields["file"].widget.attrs["class"] = "hidden"
        self.fields["file"].widget.attrs["@change"] = (
            "fileName = $event.target.files[0] ? $event.target.files[0].name : ''"
        )

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > settings.RESUME_MAX_UPLOAD_BYTES:
            max_mb = settings.RESUME_MAX_UPLOAD_BYTES // (1024 * 1024)
            raise forms.ValidationError(f"That file is too large — please keep it under {max_mb} MB.")
        return file
