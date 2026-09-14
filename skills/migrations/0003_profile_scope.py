"""Move recorded skills onto a profile.

Everything a user records now belongs to one workspace instead of the account.
Each row is handed to that user's first (until now, only) profile, so nothing
moves in the UI — it just gains an owner that can be switched.
"""

from django.db import migrations, models
import django.db.models.deletion


def link_userskill(apps, schema_editor):
    Model = apps.get_model("skills", "UserSkill")
    Profile = apps.get_model("accounts", "Profile")
    first_profile = {}
    for profile in Profile.objects.order_by("id"):
        first_profile.setdefault(profile.user_id, profile.id)
    for user_id, profile_id in first_profile.items():
        Model.objects.filter(user_id=user_id).update(profile_id=profile_id)


def unlink_userskill(apps, schema_editor):
    Model = apps.get_model("skills", "UserSkill")
    Profile = apps.get_model("accounts", "Profile")
    for profile_id, user_id in Profile.objects.values_list("id", "user_id"):
        Model.objects.filter(profile_id=profile_id).update(user_id=user_id)


class Migration(migrations.Migration):

    dependencies = [
        ("skills", "0002_seed_categories"),
        ("accounts", "0002_profile_workspaces"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="userskill",
            name="unique_skill_per_user_category",
        ),
        migrations.AddField(
            model_name="userskill",
            name="profile",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="skills",
                to="accounts.profile",
            ),
        ),
        migrations.RunPython(link_userskill, unlink_userskill),
        migrations.AlterField(
            model_name="userskill",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="skills",
                to="accounts.profile",
            ),
        ),
        migrations.RemoveField(
            model_name="userskill",
            name="user",
        ),
        migrations.AddConstraint(
            model_name="userskill",
            constraint=models.UniqueConstraint(fields=("profile", "category", "name",), name="unique_skill_per_profile_category"),
        ),
    ]
