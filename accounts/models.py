from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    """Custom user that authenticates with an email address instead of a username."""

    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.get_full_name() or self.email

    def get_short_name(self):
        return self.first_name or self.email.split("@")[0]


def avatar_upload_path(instance, filename):
    return f"avatars/user_{instance.user_id}/{filename}"


def default_profile_language() -> str:
    """The language a bootstrap profile is created with.

    Inside a request this is whatever the user is currently reading the site
    in; outside one (``createsuperuser``, a data migration, a test factory) it
    falls back to the project default.
    """
    from django.utils.translation import get_language

    available = {code for code, _name in settings.LANGUAGES}
    active = (get_language() or "")[:10]
    if active in available:
        return active
    short = active[:2]
    if short in available:
        return short
    return settings.LANGUAGE_CODE


class Profile(models.Model):
    """A workspace: one candidate persona, in one language.

    Everything a user records — skills, languages, experience, education, job
    preferences, analyzed job posts, resume imports and tailored resumes — hangs
    off exactly one profile, so a user can keep, say, a French "Data analyst"
    profile and an English "Backend engineer" profile side by side without the
    two ever bleeding into each other.

    `language` is chosen when the profile is created and never changes
    afterwards: it is the language every AI call for this profile answers in,
    and the language its generated documents are written in. Wanting another
    language means wanting another profile.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profiles"
    )
    name = models.CharField(
        _("Profile name"),
        max_length=80,
        help_text=_("e.g. “Backend engineer” or “Data analyst (FR)”."),
    )
    language = models.CharField(
        _("Language"),
        max_length=10,
        choices=settings.LANGUAGES,
        help_text=_(
            "Every AI analysis and every document generated for this profile is "
            "written in this language. It can't be changed later."
        ),
    )

    headline = models.CharField(
        _("Professional headline"),
        max_length=150,
        blank=True,
        help_text=_("e.g. “Frontend Developer looking for new opportunities”"),
    )
    phone = models.CharField(_("Phone"), max_length=30, blank=True)
    location = models.CharField(_("Location"), max_length=120, blank=True)
    bio = models.TextField(_("About me"), blank=True, max_length=2000)
    avatar = models.ImageField(_("Avatar"), upload_to=avatar_upload_path, blank=True, null=True)
    linkedin_url = models.URLField(_("LinkedIn"), blank=True)
    portfolio_url = models.URLField(_("Portfolio / website"), blank=True)
    github_url = models.URLField(_("GitHub"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_profile_name_per_user")
        ]

    def __str__(self):
        return self.name or f"Profile #{self.pk}"

    @property
    def language_label(self) -> str:
        return dict(settings.LANGUAGES).get(self.language, self.language)

    @property
    def completion_percent(self) -> int:
        fields = [
            self.headline,
            self.phone,
            self.location,
            self.bio,
            self.avatar,
            self.linkedin_url or self.portfolio_url or self.github_url,
        ]
        filled = sum(1 for f in fields if f)
        return round((filled / len(fields)) * 100)
