from django import forms
from django.conf import settings

from core.forms import TEXT_INPUT_CLASSES, StyledModelForm

from .models import ResumeImport, TailoredResume


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


class TailoredResumeForm(StyledModelForm):
    """The Markdown editor on the tailored-resume page."""

    class Meta:
        model = TailoredResume
        fields = ["markdown"]
        labels = {"markdown": "Resume (Markdown)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["markdown"]
        # The model field is blank=True (a draft can start empty), but the
        # editor should never save an empty resume. Django strips the value,
        # so a whitespace-only submission trips this too.
        field.required = True
        field.error_messages["required"] = "Your resume can't be empty."
        field.widget.attrs.update(
            {
                "rows": 28,
                "spellcheck": "true",
                "class": TEXT_INPUT_CLASSES + " font-mono text-xs leading-relaxed",
            }
        )
