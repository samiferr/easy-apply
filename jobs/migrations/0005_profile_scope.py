"""Move analyzed job posts onto a profile.

Everything a user records now belongs to one workspace instead of the account.
Each row is handed to that user's first (until now, only) profile, so nothing
moves in the UI — it just gains an owner that can be switched.
"""

from django.db import migrations, models
import django.db.models.deletion


def link_jobpost(apps, schema_editor):
    Model = apps.get_model("jobs", "JobPost")
    Profile = apps.get_model("accounts", "Profile")
    first_profile = {}
    for profile in Profile.objects.order_by("id"):
        first_profile.setdefault(profile.user_id, profile.id)
    for user_id, profile_id in first_profile.items():
        Model.objects.filter(user_id=user_id).update(profile_id=profile_id)


def unlink_jobpost(apps, schema_editor):
    Model = apps.get_model("jobs", "JobPost")
    Profile = apps.get_model("accounts", "Profile")
    for profile_id, user_id in Profile.objects.values_list("id", "user_id"):
        Model.objects.filter(profile_id=profile_id).update(user_id=user_id)


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0004_reset_analyzed_jobs"),
        ("accounts", "0002_profile_workspaces"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobpost",
            name="profile",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="job_posts",
                to="accounts.profile",
            ),
        ),
        migrations.RunPython(link_jobpost, unlink_jobpost),
        migrations.AlterField(
            model_name="jobpost",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="job_posts",
                to="accounts.profile",
            ),
        ),
        migrations.RemoveField(
            model_name="jobpost",
            name="user",
        ),
        migrations.AlterField(
            model_name="jobpost",
            name="analysis_language",
            field=models.CharField(
                blank=True,
                help_text=(
                    "The language this stored analysis is written in. Copied "
                    "from the profile at analysis time, so the record says what "
                    "it is even if the job is later read from somewhere else."
                ),
                max_length=10,
            ),
        ),
    ]
