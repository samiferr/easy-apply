from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from core.forms import StyledFormMixin

from .models import Profile, default_profile_language

User = get_user_model()

#: A profile's language must be picked, never defaulted into silently — the
#: blank first option is what forces the choice.
LANGUAGE_CHOICES = [("", _("Choose a language…")), *settings.LANGUAGES]


class RegisterForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    #: The language of the profile created for this account. Asked here rather
    #: than after signing up so the very first profile is never guessed at.
    profile_language = forms.ChoiceField(
        label=_("Profile language"),
        choices=LANGUAGE_CHOICES,
        help_text=_(
            "Your first profile — and everything the AI writes for it — uses "
            "this language. You can add profiles in other languages later."
        ),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile_language"].initial = default_profile_language()
        self.fields["password1"].help_text = (
            "Use at least 8 characters, avoid common passwords and don't make it "
            "entirely numeric."
        )
        self.fields["password2"].help_text = "Enter the same password again for verification."
        for field in self.fields.values():
            field.widget.attrs.setdefault("autocomplete", "off")
        self._style_fields()

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(StyledFormMixin, AuthenticationForm):
    username = forms.EmailField(
        label="Email address", widget=forms.EmailInput(attrs={"autofocus": True})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["remember_me"] = forms.BooleanField(required=False, initial=True)
        self._style_fields()

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "Please enter a correct email address and password. Note that both "
            "fields may be case-sensitive."
        ),
    }


class ProfileForm(StyledFormMixin, forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = Profile
        fields = [
            "headline",
            "phone",
            "location",
            "bio",
            "avatar",
            "linkedin_url",
            "portfolio_url",
            "github_url",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
        # Move name fields to the front for a natural tab order.
        self.order_fields(["first_name", "last_name", "headline", "phone", "location"])
        self._style_fields()

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user is not None:
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            if commit:
                self.user.save(update_fields=["first_name", "last_name"])
        if commit:
            profile.save()
        return profile


class BaseProfileForm(StyledFormMixin, forms.ModelForm):
    """Shared naming rules for the two profile screens."""

    class Meta:
        model = Profile
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": _("Backend engineer")})}

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError(_("Give this profile a name."))
        clash = Profile.objects.filter(user=self.user, name__iexact=name).exclude(
            pk=self.instance.pk
        )
        if clash.exists():
            raise forms.ValidationError(_("You already have a profile with that name."))
        return name


class ProfileCreateForm(BaseProfileForm):
    """The "new profile" screen.

    Only two questions, and the language is one of them: it decides what every
    later AI call for this workspace answers in, and it is fixed from here on,
    so it cannot be left to a default.
    """

    language = forms.ChoiceField(
        label=_("Language"),
        choices=LANGUAGE_CHOICES,
        help_text=_(
            "Every analysis, match and resume generated in this profile is "
            "written in this language. It can't be changed afterwards."
        ),
    )

    class Meta(BaseProfileForm.Meta):
        fields = ["name", "language"]

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.user = self.user
        if commit:
            profile.save()
        return profile


class ProfileRenameForm(BaseProfileForm):
    """Renaming an existing profile.

    The language is deliberately absent: the content already recorded under it
    is written in that language, and re-pointing the profile at another one
    would leave it permanently mixed. Another language means another profile.
    """


class AccountDeleteForm(StyledFormMixin, forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, label="Confirm your password")
    confirm = forms.BooleanField(
        label="I understand this will permanently delete my account and all my data.",
        required=True,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._style_fields()

    def clean_password(self):
        password = self.cleaned_data["password"]
        if self.user is not None and not self.user.check_password(password):
            raise forms.ValidationError("Incorrect password.")
        return password
