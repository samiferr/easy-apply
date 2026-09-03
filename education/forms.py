from django import forms

from core.forms import StyledModelForm

from .models import Certificate, Degree


class DegreeForm(StyledModelForm):
    class Meta:
        model = Degree
        fields = [
            "school",
            "degree",
            "field_of_study",
            "start_date",
            "end_date",
            "is_current",
            "grade",
            "description",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_current"):
            cleaned["end_date"] = None
        elif cleaned.get("end_date") and cleaned.get("start_date"):
            if cleaned["end_date"] < cleaned["start_date"]:
                self.add_error("end_date", "End date can't be before the start date.")
        return cleaned


class CertificateForm(StyledModelForm):
    class Meta:
        model = Certificate
        fields = [
            "name",
            "issuing_organization",
            "issue_date",
            "expiry_date",
            "does_not_expire",
            "credential_id",
            "credential_url",
        ]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("does_not_expire"):
            cleaned["expiry_date"] = None
        return cleaned
