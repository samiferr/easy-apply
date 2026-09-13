"""Turn the one-per-user Profile into a named, language-bound workspace.

Existing rows keep every personal field they had; they gain a default name and
the project's default language, which is what they were implicitly written in.
"""

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion

import accounts.models


def name_existing_profiles(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    User = apps.get_model("accounts", "User")

    Profile.objects.filter(name="").update(name="My profile")
    Profile.objects.filter(language="").update(language=settings.LANGUAGE_CODE)

    # Every account must own at least one profile: the migrations that follow
    # move all of its content onto one, and a user without a profile would
    # leave orphan rows that can't be made non-null.
    with_profile = set(Profile.objects.values_list("user_id", flat=True))
    Profile.objects.bulk_create(
        Profile(user_id=user_id, name="My profile", language=settings.LANGUAGE_CODE)
        for user_id in User.objects.exclude(pk__in=with_profile).values_list("pk", flat=True)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="name",
            field=models.CharField(
                default="",
                help_text="e.g. “Backend engineer” or “Data analyst (FR)”.",
                max_length=80,
                verbose_name="Profile name",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="profile",
            name="language",
            field=models.CharField(
                choices=settings.LANGUAGES,
                default="",
                help_text=(
                    "Every AI analysis and every document generated for this "
                    "profile is written in this language. It can't be changed later."
                ),
                max_length=10,
                verbose_name="Language",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="profile",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.RunPython(name_existing_profiles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="profile",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="profiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="avatar",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=accounts.models.avatar_upload_path,
                verbose_name="Avatar",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="bio",
            field=models.TextField(blank=True, max_length=2000, verbose_name="About me"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="github_url",
            field=models.URLField(blank=True, verbose_name="GitHub"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="headline",
            field=models.CharField(
                blank=True,
                help_text="e.g. “Frontend Developer looking for new opportunities”",
                max_length=150,
                verbose_name="Professional headline",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="linkedin_url",
            field=models.URLField(blank=True, verbose_name="LinkedIn"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="location",
            field=models.CharField(blank=True, max_length=120, verbose_name="Location"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="phone",
            field=models.CharField(blank=True, max_length=30, verbose_name="Phone"),
        ),
        migrations.AlterField(
            model_name="profile",
            name="portfolio_url",
            field=models.URLField(blank=True, verbose_name="Portfolio / website"),
        ),
        migrations.AlterModelOptions(
            name="profile",
            options={
                "ordering": ["created_at", "id"],
                "verbose_name": "profile",
                "verbose_name_plural": "profiles",
            },
        ),
        migrations.AddConstraint(
            model_name="profile",
            constraint=models.UniqueConstraint(
                fields=("user", "name"), name="unique_profile_name_per_user"
            ),
        ),
    ]
