"""Apply the audit-log retention policy.

Entries are deleted through the queryset rather than one at a time: the model
refuses individual deletes on purpose, so that nothing in a view can quietly
remove a single inconvenient row.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from staffportal.models import AuditLog
from staffportal.services import runtime_settings


class Command(BaseCommand):
    help = "Delete audit entries older than the configured retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        verbose = options.get("verbosity", 1)
        days = options["days"] or int(runtime_settings.get("audit_retention_days"))
        cutoff = timezone.now() - timedelta(days=days)
        stale = AuditLog.objects.filter(created_at__lt=cutoff)
        count = stale.count()
        if options["dry_run"]:
            if verbose:
                self.stdout.write(f"Would delete {count} entries older than {days} days.")
            return
        stale.delete()
        if verbose:
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {count} entries older than {days} days.")
            )
