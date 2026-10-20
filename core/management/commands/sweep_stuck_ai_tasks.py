"""Fail AI tasks left running by a killed worker.

Run this on worker startup so a crash never leaves a permanent spinner in
the UI (spec §7.7). The rule itself lives in `core.services.sweep_stuck_tasks`.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from core import services


class Command(BaseCommand):
    help = "Mark AI tasks stuck in queued/running with no recent update as failed."

    def add_arguments(self, parser):
        parser.add_argument("--seconds", type=int, default=settings.AI_TASK_STALE_AFTER)

    def handle(self, *args, **options):
        count = services.sweep_stuck_tasks(options["seconds"])
        self.stdout.write(self.style.SUCCESS(f"Swept {count} stuck AI task(s)."))
