from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse

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


class Profile(models.Model):
    """Extra, editable profile information shown on the personal recap."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    headline = models.CharField(
        "Professional headline",
        max_length=150,
        blank=True,
        help_text="e.g. “Frontend Developer looking for new opportunities”",
    )
    phone = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=120, blank=True)
    bio = models.TextField("About me", blank=True, max_length=2000)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True, null=True)
    linkedin_url = models.URLField("LinkedIn", blank=True)
    portfolio_url = models.URLField("Portfolio / website", blank=True)
    github_url = models.URLField("GitHub", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"

    def get_absolute_url(self):
        return reverse("accounts:profile")

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
