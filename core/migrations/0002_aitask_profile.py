"""Record which workspace an AI task was started from.

`user` stays: the polling endpoint authorizes by account. `profile` is what the
dashboard filters on, so a run started in one workspace never shows up in
another.
"""

from django.db import migrations, models
import django.db.models.deletion


def link_tasks_to_profile(apps, schema_editor):
    AITask = apps.get_model("core", "AITask")
    Profile = apps.get_model("accounts", "Profile")
    first_profile = {}
    for profile in Profile.objects.order_by("id"):
        first_profile.setdefault(profile.user_id, profile.id)
    for user_id, profile_id in first_profile.items():
        AITask.objects.filter(user_id=user_id).update(profile_id=profile_id)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("accounts", "0002_profile_workspaces"),
    ]

    operations = [
        migrations.AddField(
            model_name="aitask",
            name="profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ai_tasks",
                to="accounts.profile",
            ),
        ),
        migrations.RunPython(link_tasks_to_profile, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="aitask",
            index=models.Index(fields=["profile", "state"], name="core_aitask_profile_d3e514_idx"),
        ),
    ]
