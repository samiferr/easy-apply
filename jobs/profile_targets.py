"""The "Add to my profile" registry.

Each matched section names an `add_target` in jobs/sections.py; this module
maps that name to the form the modal renders and the object it creates. Adding
a section later is one entry here, not a chain of `if` branches.

Every handler is responsible for rejecting duplicates against the existing
UniqueConstraints and surfacing the conflict as a form error rather than a 500.
"""

from dataclasses import dataclass

from django import forms
from django.utils.translation import gettext_lazy as _

from education.models import Certificate, Degree
from experience.models import ExperienceHighlight, WorkExperience
from languages.models import Language, UserLanguage
from preferences.models import BenefitPreference, get_or_create_preference
from skills.models import SkillCategory, UserSkill


# ---------------------------------------------------------------------------
# Forms — each pre-filled from the element text, then reviewed by the user.
# ---------------------------------------------------------------------------
class BaseAddForm(forms.Form):
    """Every add-to-profile form gets the user and the source element."""

    def __init__(self, *args, user=None, element=None, **kwargs):
        self.user = user
        self.element = element
        super().__init__(*args, **kwargs)

    def save(self):  # pragma: no cover - implemented by subclasses
        raise NotImplementedError


class SkillAddForm(BaseAddForm):
    kind = SkillCategory.TECHNICAL

    name = forms.CharField(label=_("Skill"), max_length=100)
    category = forms.ModelChoiceField(label=_("Category"), queryset=SkillCategory.objects.none())
    level = forms.TypedChoiceField(
        label=_("Level"), choices=UserSkill.LEVEL_CHOICES, coerce=int,
        initial=UserSkill.INTERMEDIATE,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = SkillCategory.objects.filter(kind=self.kind)
        self.fields["category"].queryset = categories
        if not self.initial.get("category") and categories.exists():
            self.fields["category"].initial = categories.first().pk

    def clean(self):
        cleaned = super().clean()
        name, category = cleaned.get("name"), cleaned.get("category")
        if name and category:
            exists = UserSkill.objects.filter(
                user=self.user, category=category, name__iexact=name.strip()
            ).exists()
            if exists:
                raise forms.ValidationError(
                    _("“%(name)s” is already in that category on your profile.")
                    % {"name": name}
                )
        return cleaned

    def save(self):
        return UserSkill.objects.create(
            user=self.user,
            category=self.cleaned_data["category"],
            name=self.cleaned_data["name"].strip(),
            level=self.cleaned_data["level"],
        )


class SoftSkillAddForm(SkillAddForm):
    kind = SkillCategory.SOFT


class LanguageAddForm(BaseAddForm):
    name = forms.CharField(label=_("Language"), max_length=80)
    proficiency = forms.ChoiceField(
        label=_("Proficiency"),
        choices=UserLanguage.PROFICIENCY_CHOICES,
        initial=UserLanguage.PROFESSIONAL,
    )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        existing = Language.objects.filter(name__iexact=name).first()
        if existing and UserLanguage.objects.filter(user=self.user, language=existing).exists():
            raise forms.ValidationError(
                _("%(name)s is already on your profile.") % {"name": existing.name}
            )
        return name

    def save(self):
        language, _created = Language.objects.get_or_create(
            name__iexact=self.cleaned_data["name"],
            defaults={"name": self.cleaned_data["name"]},
        )
        return UserLanguage.objects.create(
            user=self.user, language=language, proficiency=self.cleaned_data["proficiency"]
        )


class ExperienceHighlightAddForm(BaseAddForm):
    experience = forms.ModelChoiceField(
        label=_("Add to which role?"), queryset=WorkExperience.objects.none()
    )
    text = forms.CharField(label=_("Highlight"), max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        experiences = WorkExperience.objects.filter(user=self.user)
        self.fields["experience"].queryset = experiences
        if experiences.exists() and not self.initial.get("experience"):
            self.fields["experience"].initial = experiences.first().pk
        else:
            self.fields["experience"].help_text = _(
                "Add a work experience to your profile first, then come back."
            )

    def save(self):
        experience = self.cleaned_data["experience"]
        order = experience.highlights.count()
        return ExperienceHighlight.objects.create(
            experience=experience, text=self.cleaned_data["text"].strip(), order=order
        )


class EducationAddForm(BaseAddForm):
    """One modal that creates either a Degree or a Certificate."""

    RECORD_DEGREE = "degree"
    RECORD_CERTIFICATE = "certificate"

    record_type = forms.ChoiceField(
        label=_("Record as"),
        choices=[(RECORD_DEGREE, _("Degree")), (RECORD_CERTIFICATE, _("Certificate"))],
        initial=RECORD_DEGREE,
        widget=forms.RadioSelect,
    )
    title = forms.CharField(label=_("Degree or certificate name"), max_length=150)
    organization = forms.CharField(
        label=_("School or issuing organization"), max_length=150, required=False
    )
    field_of_study = forms.CharField(label=_("Field of study"), max_length=150, required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("record_type") == self.RECORD_CERTIFICATE and not cleaned.get("organization"):
            self.add_error("organization", _("Certificates need an issuing organization."))
        return cleaned

    def save(self):
        if self.cleaned_data["record_type"] == self.RECORD_CERTIFICATE:
            return Certificate.objects.create(
                user=self.user,
                name=self.cleaned_data["title"].strip(),
                issuing_organization=self.cleaned_data["organization"].strip(),
            )
        return Degree.objects.create(
            user=self.user,
            degree=self.cleaned_data["title"].strip(),
            school=self.cleaned_data["organization"].strip() or "—",
            field_of_study=self.cleaned_data["field_of_study"].strip(),
        )


class BenefitAddForm(BaseAddForm):
    name = forms.CharField(label=_("Benefit"), max_length=120)
    importance = forms.ChoiceField(
        label=_("Importance"),
        choices=BenefitPreference.IMPORTANCE_CHOICES,
        initial=BenefitPreference.NICE_TO_HAVE,
    )
    notes = forms.CharField(label=_("Notes"), max_length=250, required=False)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        preference = get_or_create_preference(self.user)
        if preference.benefits.filter(name__iexact=name).exists():
            raise forms.ValidationError(
                _("“%(name)s” is already in your preferences.") % {"name": name}
            )
        return name

    def save(self):
        preference = get_or_create_preference(self.user)
        return BenefitPreference.objects.create(
            preference=preference,
            name=self.cleaned_data["name"],
            importance=self.cleaned_data["importance"],
            notes=self.cleaned_data["notes"].strip(),
        )


class LocationPreferenceAddForm(BaseAddForm):
    """Writes onto the scalar JobPreference fields rather than creating a row."""

    ADD_LOCATION = "location"
    SET_ARRANGEMENT = "arrangement"
    SET_TIMEZONE = "timezone"
    SET_TRAVEL = "travel"

    apply_to = forms.ChoiceField(
        label=_("Record this as"),
        choices=[
            (ADD_LOCATION, _("A preferred location")),
            (SET_ARRANGEMENT, _("An acceptable work arrangement")),
            (SET_TIMEZONE, _("My time zone preference")),
            (SET_TRAVEL, _("Maximum travel I accept")),
        ],
        initial=ADD_LOCATION,
    )
    value = forms.CharField(label=_("Value"), max_length=200)
    arrangement = forms.ChoiceField(
        label=_("Arrangement"),
        choices=[("remote", _("Remote")), ("hybrid", _("Hybrid")), ("onsite", _("On-site"))],
        required=False,
    )
    travel_percentage = forms.IntegerField(
        label=_("Max. travel (%)"), min_value=0, max_value=100, required=False
    )

    def clean(self):
        cleaned = super().clean()
        apply_to = cleaned.get("apply_to")
        if apply_to == self.SET_ARRANGEMENT and not cleaned.get("arrangement"):
            self.add_error("arrangement", _("Pick which arrangement this is."))
        if apply_to == self.SET_TRAVEL and cleaned.get("travel_percentage") is None:
            self.add_error("travel_percentage", _("Give a maximum travel percentage."))
        return cleaned

    def save(self):
        preference = get_or_create_preference(self.user)
        apply_to = self.cleaned_data["apply_to"]
        value = self.cleaned_data["value"].strip()

        if apply_to == self.ADD_LOCATION:
            existing = preference.preferred_locations_list
            if value.lower() not in [item.lower() for item in existing]:
                existing.append(value)
            preference.preferred_locations = "\n".join(existing)
            preference.save(update_fields=["preferred_locations", "updated_at"])
        elif apply_to == self.SET_ARRANGEMENT:
            field = {
                "remote": "remote_ok",
                "hybrid": "hybrid_ok",
                "onsite": "onsite_ok",
            }[self.cleaned_data["arrangement"]]
            setattr(preference, field, True)
            preference.save(update_fields=[field, "updated_at"])
        elif apply_to == self.SET_TIMEZONE:
            preference.timezone_preference = value[:120]
            preference.save(update_fields=["timezone_preference", "updated_at"])
        else:
            preference.max_travel_percentage = self.cleaned_data["travel_percentage"]
            preference.save(update_fields=["max_travel_percentage", "updated_at"])
        return preference


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AddTarget:
    key: str
    form_class: type
    title: object
    help_text: object = ""

    def initial_for(self, element) -> dict:
        """Pre-fill the form from the element's text."""
        text = (element.text or "").strip()
        if self.form_class in (SkillAddForm, SoftSkillAddForm):
            return {"name": text[:100]}
        if self.form_class is LanguageAddForm:
            # "French — professional working proficiency" -> "French"
            head = text.split("—")[0].split("-")[0].split("(")[0]
            return {"name": head.strip()[:80] or text[:80]}
        if self.form_class is ExperienceHighlightAddForm:
            return {"text": text[:500]}
        if self.form_class is EducationAddForm:
            return {"title": text[:150]}
        if self.form_class is BenefitAddForm:
            return {"name": text[:120]}
        if self.form_class is LocationPreferenceAddForm:
            return {"value": text[:200]}
        return {}


ADD_TARGETS: dict[str, AddTarget] = {
    "technical_skill": AddTarget(
        key="technical_skill",
        form_class=SkillAddForm,
        title=_("Add to my technical skills"),
        help_text=_("Review the name and level before adding it to your profile."),
    ),
    "soft_skill": AddTarget(
        key="soft_skill",
        form_class=SoftSkillAddForm,
        title=_("Add to my soft skills"),
        help_text=_("Review the name and level before adding it to your profile."),
    ),
    "language": AddTarget(
        key="language",
        form_class=LanguageAddForm,
        title=_("Add to my languages"),
        help_text=_("Set the proficiency that actually matches yours."),
    ),
    "experience_highlight": AddTarget(
        key="experience_highlight",
        form_class=ExperienceHighlightAddForm,
        title=_("Add to my experience"),
        help_text=_("Reword this in your own terms, then pick the role it belongs to."),
    ),
    "education": AddTarget(
        key="education",
        form_class=EducationAddForm,
        title=_("Add to my education"),
        help_text=_("Record this as a degree or as a certificate."),
    ),
    "benefit_preference": AddTarget(
        key="benefit_preference",
        form_class=BenefitAddForm,
        title=_("Add to my job preferences"),
        help_text=_("Say how much this benefit matters to you."),
    ),
    "job_preference_location": AddTarget(
        key="job_preference_location",
        form_class=LocationPreferenceAddForm,
        title=_("Add to my job preferences"),
        help_text=_("Choose which preference this fact should update."),
    ),
}


def get_add_target(section_key: str) -> AddTarget | None:
    from .sections import get_section

    section = get_section(section_key)
    if section is None or not section.add_target:
        return None
    return ADD_TARGETS.get(section.add_target)
