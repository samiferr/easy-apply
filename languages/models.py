from django.conf import settings
from django.db import models


class Language(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserLanguage(models.Model):
    BASIC = "basic"
    CONVERSATIONAL = "conversational"
    PROFESSIONAL = "professional"
    FLUENT = "fluent"
    NATIVE = "native"
    PROFICIENCY_CHOICES = [
        (BASIC, "Basic"),
        (CONVERSATIONAL, "Conversational"),
        (PROFESSIONAL, "Professional working proficiency"),
        (FLUENT, "Fluent"),
        (NATIVE, "Native / bilingual"),
    ]
    PROFICIENCY_ORDER = {choice[0]: i for i, choice in enumerate(PROFICIENCY_CHOICES)}

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="languages"
    )
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="speakers")
    proficiency = models.CharField(
        max_length=20, choices=PROFICIENCY_CHOICES, default=CONVERSATIONAL
    )

    class Meta:
        ordering = ["language__name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "language"], name="unique_language_per_user")
        ]

    def __str__(self):
        return f"{self.language} — {self.get_proficiency_display()}"

    @property
    def proficiency_percent(self):
        steps = len(self.PROFICIENCY_CHOICES)
        return round(((self.PROFICIENCY_ORDER[self.proficiency] + 1) / steps) * 100)
