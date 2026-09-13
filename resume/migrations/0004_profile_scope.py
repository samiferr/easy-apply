"""Move resume imports and tailored resumes onto a profile.

Everything a user records now belongs to one workspace instead of the account.
Each row is handed to that user's first (until now, only) profile, so nothing
moves in the UI — it just gains an owner that can be switched.
"""

from django.db import migrations, models
import django.db.models.deletion


def link_resumeimport(apps, schema_editor):
    Model = apps.get_model("resume", "ResumeImport")
    Profile = apps.get_model("accounts", "Profile")
    first_profile = {}
    for profile in Profile.objects.order_by("id"):
        first_profile.setdefault(profile.user_id, profile.id)
    for user_id, profile_id in first_profile.items():
        Model.objects.filter(user_id=user_id).update(profile_id=profile_id)


def unlink_resumeimport(apps, schema_editor):
    Model = apps.get_model("resume", "ResumeImport")
    Profile = apps.get_model("accounts", "Profile")
    for profile_id, user_id in Profile.objects.values_list("id", "user_id"):
        Model.objects.filter(profile_id=profile_id).update(user_id=user_id)


def link_tailoredresume(apps, schema_editor):
    Model = apps.get_model("resume", "TailoredResume")
    Profile = apps.get_model("accounts", "Profile")
    first_profile = {}
    for profile in Profile.objects.order_by("id"):
        first_profile.setdefault(profile.user_id, profile.id)
    for user_id, profile_id in first_profile.items():
        Model.objects.filter(user_id=user_id).update(profile_id=profile_id)


def unlink_tailoredresume(apps, schema_editor):
    Model = apps.get_model("resume", "TailoredResume")
    Profile = apps.get_model("accounts", "Profile")
    for profile_id, user_id in Profile.objects.values_list("id", "user_id"):
        Model.objects.filter(profile_id=profile_id).update(user_id=user_id)


class Migration(migrations.Migration):

    dependencies = [
        ("resume", "0003_fixed_sections"),
        ("accounts", "0002_profile_workspaces"),
    ]

    operations = [
        migrations.AddField(
            model_name="resumeimport",
            name="profile",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="resume_imports",
                to="accounts.profile",
            ),
        ),
        migrations.RunPython(link_resumeimport, unlink_resumeimport),
        migrations.AlterField(
            model_name="resumeimport",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="resume_imports",
                to="accounts.profile",
            ),
        ),
        migrations.RemoveField(
            model_name="resumeimport",
            name="user",
        ),
        migrations.AddField(
            model_name="tailoredresume",
            name="profile",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tailored_resumes",
                to="accounts.profile",
            ),
        ),
        migrations.RunPython(link_tailoredresume, unlink_tailoredresume),
        migrations.AlterField(
            model_name="tailoredresume",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tailored_resumes",
                to="accounts.profile",
            ),
        ),
        migrations.RemoveField(
            model_name="tailoredresume",
            name="user",
        ),
    ]
