"""Force re-analysis of every job imported before the fixed-section refactor.

Migration 0003 dropped RequirementCategory/Requirement outright, so previously
analyzed jobs now have no sections at all. Rather than leave them looking
"completed" but empty, reset them to pending: the detail page then shows the
"Re-analyze this job post" prompt.

This is the deliberate wipe-and-re-analyze path from the refactor spec §3.4 —
existing match verdicts are not preserved.
"""

from django.db import migrations


def reset_analyzed_jobs(apps, schema_editor):
    JobPost = apps.get_model("jobs", "JobPost")
    JobPost.objects.exclude(analyzed_at=None).update(
        status="pending",
        analyzed_at=None,
        profile_matched_at=None,
        error_message="",
    )


def noop(apps, schema_editor):
    """Irreversible: the old categories are already gone."""


class Migration(migrations.Migration):
    dependencies = [("jobs", "0003_fixed_sections")]

    operations = [migrations.RunPython(reset_analyzed_jobs, noop)]
