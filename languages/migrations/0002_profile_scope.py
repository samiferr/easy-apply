"""Move spoken languages onto a profile.

Everything a user records now belongs to one workspace instead of the account.
Each row is handed to that user's first (until now, only) profile, so nothing
moves in the UI — it just gains an owner that can be switched.
"""

from django.db import migrations, models
import django.db.models.deletion


def link_userlanguage(apps, schema_editor):
    Model = apps.get_model("languages", "UserLanguage")
    Profile = apps.get_model("accounts", "Profile")
    first_profile = {}
    for profile in Profile.objects.order_by("id"):
        first_profile.setdefault(profile.user_id, profile.id)
    for user_id, profile_id in first_profile.items():
        Model.objects.filter(user_id=user_id).update(profile_id=profile_id)


def unlink_userlanguage(apps, schema_editor):
    Model = apps.get_model("languages", "UserLanguage")
    Profile = apps.get_model("accounts", "Profile")
    for profile_id, user_id in Profile.objects.values_list("id", "user_id"):
        Model.objects.filter(profile_id=profile_id).update(user_id=user_id)


class Migration(migrations.Migration):

    dependencies = [
        ("languages", "0001_initial"),
        ("accounts", "0002_profile_workspaces"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="userlanguage",
            name="unique_language_per_user",
        ),
        migrations.AddField(
            model_name="userlanguage",
            name="profile",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="languages",
                to="accounts.profile",
            ),
        ),
        migrations.RunPython(link_userlanguage, unlink_userlanguage),
        migrations.AlterField(
            model_name="userlanguage",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="languages",
                to="accounts.profile",
            ),
        ),
        migrations.RemoveField(
            model_name="userlanguage",
            name="user",
        ),
        migrations.AddConstraint(
            model_name="userlanguage",
            constraint=models.UniqueConstraint(fields=("profile", "language",), name="unique_language_per_profile"),
        ),
    ]
