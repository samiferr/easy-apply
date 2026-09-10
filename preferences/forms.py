from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import StyledFormMixin

from .models import BenefitPreference, JobPreference


class JobPreferenceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JobPreference
        fields = [
            "desired_salary_min",
            "desired_salary_max",
            "salary_currency",
            "salary_period",
            "preferred_locations",
            "remote_ok",
            "hybrid_ok",
            "onsite_ok",
            "max_onsite_days_per_week",
            "willing_to_relocate",
            "max_travel_percentage",
            "timezone_preference",
            "employment_types",
            "availability_notes",
        ]
        widgets = {
            "preferred_locations": forms.Textarea(
                attrs={"rows": 3, "placeholder": _("Montréal, QC\nRemote (Canada)")}
            ),
            "availability_notes": forms.Textarea(
                attrs={"rows": 2, "placeholder": _("Available from March, 4 weeks notice")}
            ),
            "salary_currency": forms.TextInput(attrs={"placeholder": "CAD"}),
            "timezone_preference": forms.TextInput(attrs={"placeholder": _("EST ±2h")}),
            "employment_types": forms.TextInput(
                attrs={"placeholder": _("Full-time, Contract")}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        low, high = cleaned.get("desired_salary_min"), cleaned.get("desired_salary_max")
        if low and high and low > high:
            self.add_error(
                "desired_salary_max", _("The target salary can't be below the minimum.")
            )
        return cleaned


class BenefitPreferenceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BenefitPreference
        fields = ["name", "importance", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("Benefit")}),
            "notes": forms.TextInput(attrs={"placeholder": _("Notes")}),
        }

    def __init__(self, *args, preference=None, **kwargs):
        self.preference = preference
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError(_("Give this benefit a name."))
        qs = BenefitPreference.objects.filter(preference=self.preference, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("“%(name)s” is already in your preferences.") % {"name": name})
        return name
