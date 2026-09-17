from django.db import migrations, models


class Migration(migrations.Migration):
    """Analysis runs on pasted text only — the URL and its fetch bookkeeping go.

    `manual_text` is renamed rather than dropped and re-added: it already holds
    the pasted description for every job that was analyzed that way.
    """

    dependencies = [
        ("jobs", "0005_profile_scope"),
    ]

    operations = [
        migrations.RenameField(
            model_name="jobpost",
            old_name="manual_text",
            new_name="description_text",
        ),
        migrations.AlterField(
            model_name="jobpost",
            name="description_text",
            field=models.TextField(
                blank=True,
                help_text="The job description text the analysis was run on.",
            ),
        ),
        migrations.RemoveField(model_name="jobpost", name="source_url"),
        migrations.RemoveField(model_name="jobpost", name="fetched_at"),
    ]
