from django import forms

from core.forms import StyledModelForm

from .models import JobPost


class JobAnalysisForm(StyledModelForm):
    """The only input is the posting's text — the app never fetches a URL."""

    class Meta:
        model = JobPost
        fields = ["description_text"]
        labels = {
            "description_text": "Job description",
        }
        widgets = {
            "description_text": forms.Textarea(attrs={"rows": 16}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["description_text"]
        field.required = True
        field.widget.attrs["placeholder"] = (
            "Paste the full job posting here — title, responsibilities, "
            "requirements, benefits, everything the page says."
        )
        field.help_text = (
            "Copy the posting from the careers page and paste it here. "
            "The more complete the text, the better the analysis."
        )

    def clean_description_text(self):
        text = (self.cleaned_data.get("description_text") or "").strip()
        if len(text) < 100:
            raise forms.ValidationError(
                "That's too short to analyze — paste the full job posting."
            )
        return text
