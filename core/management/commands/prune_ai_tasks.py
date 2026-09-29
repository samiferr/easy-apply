"""Delete terminal AITask rows older than settings.AI_TASK_RETENTION_DAYS.

The rule itself lives in `core.services.prune_finished_tasks`.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from core import services


class Command(BaseCommand):
    help = "Prune finished AI task records older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.AI_TASK_RETENTION_DAYS,
            help="Retention window in days (default: settings.AI_TASK_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would be deleted."
        )

    def handle(self, *args, **options):
        count, cutoff = services.prune_finished_tasks(options["days"], dry_run=options["dry_run"])
        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} AI task(s) finished before {cutoff:%Y-%m-%d}.")
            return
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} AI task(s)."))
