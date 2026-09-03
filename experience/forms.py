from django import forms

from core.forms import StyledModelForm

from .models import WorkExperience


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
            "description",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_current"):
            cleaned["end_date"] = None
        elif cleaned.get("end_date") and cleaned.get("start_date"):
            if cleaned["end_date"] < cleaned["start_date"]:
                self.add_error("end_date", "End date can't be before the start date.")
        return cleaned
