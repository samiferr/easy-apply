from django import forms

from core.forms import StyledModelForm

from .models import Language, UserLanguage


class UserLanguageForm(StyledModelForm):
    language_name = forms.CharField(
        max_length=80,
        label="Language",
        help_text="Start typing — pick an existing language or add a new one.",
    )

    class Meta:
        model = UserLanguage
        fields = ["proficiency"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.order_fields(["language_name", "proficiency"])
        if self.instance.pk:
            self.fields["language_name"].initial = self.instance.language.name
        self._style_fields()

    def clean_language_name(self):
        name = self.cleaned_data["language_name"].strip()
        if not name:
            raise forms.ValidationError("Please enter a language.")
        existing = (
            UserLanguage.objects.filter(user=self.user, language__name__iexact=name)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if existing:
            raise forms.ValidationError("You've already added this language.")
        return name

    def save(self, commit=True):
        language, _ = Language.objects.get_or_create(
            name__iexact=self.cleaned_data["language_name"],
            defaults={"name": self.cleaned_data["language_name"]},
        )
        instance = super().save(commit=False)
        instance.language = language
        if self.user is not None:
            instance.user = self.user
        if commit:
            instance.save()
        return instance
