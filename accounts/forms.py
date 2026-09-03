from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from core.forms import StyledFormMixin

from .models import Profile

User = get_user_model()


class RegisterForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
