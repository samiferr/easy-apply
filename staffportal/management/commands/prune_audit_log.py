"""Apply the audit-log retention policy (UC-08.10).

The policy itself is `staffportal.services.prune_audit_log`; this is the
scheduled entry point to it.
"""

from django.core.management.base import BaseCommand

from staffportal import services


class Command(BaseCommand):
    help = "Delete audit entries older than the configured retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        verbose = options.get("verbosity", 1)
        count, days = services.prune_audit_log(options["days"], dry_run=options["dry_run"])
        if options["dry_run"]:
            if verbose:
                self.stdout.write(f"Would delete {count} entries older than {days} days.")
            return
        if verbose:
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {count} entries older than {days} days.")
            )
