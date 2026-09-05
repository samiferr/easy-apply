from django import forms
from django.forms import inlineformset_factory

from core.forms import StyledModelForm

from .models import ExperienceHighlight, WorkExperience


class WorkExperienceForm(StyledModelForm):
    class Meta:
        model = WorkExperience
        fields = [
            "job_title",
            "company",
            "location",
            "employment_type",
            "start_date",
            "end_date",
            "is_current",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_current"):
            cleaned["end_date"] = None
        elif cleaned.get("end_date") and cleaned.get("start_date"):
            if cleaned["end_date"] < cleaned["start_date"]:
                self.add_error("end_date", "End date can't be before the start date.")
        return cleaned


class HighlightForm(StyledModelForm):
    class Meta:
        model = ExperienceHighlight
        fields = ["text"]
        labels = {"text": ""}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].required = False
        self.fields["text"].widget.attrs["placeholder"] = (
            "e.g. Led the migration to a microservices architecture, cutting "
            "deploy time by 40%."
        )


HighlightFormSet = inlineformset_factory(
    WorkExperience,
    ExperienceHighlight,
    form=HighlightForm,
    fields=["text"],
    extra=1,
    can_delete=True,
    max_num=20,
    validate_max=True,
)
