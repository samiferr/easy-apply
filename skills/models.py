from django.db import models
from django.utils.translation import gettext_lazy as _


class SkillCategory(models.Model):
    SOFT = "soft"
    TECHNICAL = "technical"
    KIND_CHOICES = [
        (SOFT, _("Soft skill")),
        (TECHNICAL, _("Technical skill")),
    ]

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Optional short label or emoji shown next to the category.",
    )

    class Meta:
        verbose_name_plural = "skill categories"
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "kind"], name="unique_category_per_kind")
        ]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


class UserSkill(models.Model):
    BEGINNER = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4
    LEVEL_CHOICES = [
        (BEGINNER, _("Beginner")),
        (INTERMEDIATE, _("Intermediate")),
        (ADVANCED, _("Advanced")),
        (EXPERT, _("Expert")),
    ]

    profile = models.ForeignKey(
        "accounts.Profile", on_delete=models.CASCADE, related_name="skills"
    )
    category = models.ForeignKey(
        SkillCategory, on_delete=models.PROTECT, related_name="user_skills"
    )
    name = models.CharField(max_length=100)
    level = models.PositiveSmallIntegerField(choices=LEVEL_CHOICES, default=INTERMEDIATE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__name", "-level", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "category", "name"],
                name="unique_skill_per_profile_category",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.get_level_display()}"

    @property
    def kind(self):
        return self.category.kind

    @property
    def level_percent(self):
        return round((self.level / self.EXPERT) * 100)
