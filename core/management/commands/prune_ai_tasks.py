"""Delete terminal AITask rows older than settings.AI_TASK_RETENTION_DAYS."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AITask


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
        cutoff = timezone.now() - timedelta(days=options["days"])
        qs = AITask.objects.filter(
            state__in=AITask.TERMINAL_STATES, finished_at__lt=cutoff
        )
        count = qs.count()
        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} AI task(s) finished before {cutoff:%Y-%m-%d}.")
            return
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} AI task(s)."))
