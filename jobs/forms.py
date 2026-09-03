from django import forms

from core.forms import StyledModelForm

from .models import JobPost


class JobAnalysisForm(StyledModelForm):
    class Meta:
        model = JobPost
        fields = ["source_url", "manual_text"]
        labels = {
            "source_url": "Job posting URL",
            "manual_text": "Or paste the job description text",
        }
        widgets = {
            "manual_text": forms.Textarea(attrs={"rows": 10}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_url"].widget.attrs["placeholder"] = (
            "https://company.com/careers/senior-backend-engineer"
        )
        self.fields["manual_text"].required = False
        self.fields["manual_text"].help_text = (
            "Optional — use this if the site blocks automated fetching or needs "
            "JavaScript to load its content."
        )
