"""Fail AI tasks left running by a killed worker.

Run this on worker startup so a crash never leaves a permanent spinner in
the UI (spec §7.7).
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AITask


class Command(BaseCommand):
    help = "Mark AI tasks stuck in queued/running with no recent update as failed."

    def add_arguments(self, parser):
        parser.add_argument("--seconds", type=int, default=settings.AI_TASK_STALE_AFTER)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(seconds=options["seconds"])
        stuck = AITask.objects.filter(
            state__in=[AITask.QUEUED, AITask.RUNNING], updated_at__lt=cutoff
        )
        count = stuck.count()
        stuck.update(
            state=AITask.FAILED,
            error_message="This run was interrupted. Please try again.",
            finished_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"Swept {count} stuck AI task(s)."))
