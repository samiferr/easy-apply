from django.db import migrations

SOFT_CATEGORIES = [
    "Communication",
    "Leadership",
    "Teamwork & Collaboration",
    "Problem Solving",
    "Time Management",
    "Adaptability",
]

TECHNICAL_CATEGORIES = [
    "Programming Languages",
    "Frameworks & Libraries",
    "Databases",
    "Cloud & DevOps",
    "Tools & Platforms",
    "Design & Data",
]


def seed_categories(apps, schema_editor):
    SkillCategory = apps.get_model("skills", "SkillCategory")
    for name in SOFT_CATEGORIES:
        SkillCategory.objects.get_or_create(name=name, kind="soft")
    for name in TECHNICAL_CATEGORIES:
        SkillCategory.objects.get_or_create(name=name, kind="technical")


def remove_seeded_categories(apps, schema_editor):
    SkillCategory = apps.get_model("skills", "SkillCategory")
    SkillCategory.objects.filter(name__in=SOFT_CATEGORIES, kind="soft").delete()
    SkillCategory.objects.filter(name__in=TECHNICAL_CATEGORIES, kind="technical").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_categories, remove_seeded_categories),
    ]
