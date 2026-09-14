"""Shared cross-app models.

`AITask` is the single progress record every AI operation reports through, so
the UI has one polling contract and one progress widget instead of four.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AITask(models.Model):
    RESUME_IMPORT = "resume_import"
    JOB_ANALYSIS = "job_analysis"
    JOB_MATCH = "job_match"
    TAILORED_RESUME = "tailored_resume"
    KIND_CHOICES = [
        (RESUME_IMPORT, _("Resume analysis")),
        (JOB_ANALYSIS, _("Job analysis")),
        (JOB_MATCH, _("Matching analysis")),
        (TAILORED_RESUME, _("Resume generation")),
    ]

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"
    STATE_CHOICES = [
        (QUEUED, _("Queued")),
        (RUNNING, _("Running")),
        (DONE, _("Done")),
        (FAILED, _("Failed")),
        (CANCELED, _("Canceled")),
    ]
    TERMINAL_STATES = {DONE, FAILED, CANCELED}

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_tasks"
    )
    # The workspace the task belongs to. Kept alongside `user` because the
    # polling endpoint authorizes by account, while the dashboard only ever
    # shows what is running in the profile you are looking at.
    profile = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.CASCADE,
        related_name="ai_tasks",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=QUEUED)

    # Generic link to whatever the task is about: JobPost, ResumeImport, TailoredResume.
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    celery_task_id = models.CharField(max_length=100, blank=True, db_index=True)
    steps_total = models.PositiveSmallIntegerField(default=1)
    steps_done = models.PositiveSmallIntegerField(default=0)
    current_step = models.CharField(max_length=200, blank=True)
    error_message = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-queued_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["user", "state"]),
            models.Index(fields=["profile", "state"]),
        ]
        verbose_name = _("AI task")
        verbose_name_plural = _("AI tasks")

    def __str__(self):
        return f"{self.get_kind_display()} — {self.get_state_display()}"

    # --- Progress --------------------------------------------------------
    @property
    def is_indeterminate(self) -> bool:
        """A single-step task has no meaningful percentage — the UI renders a
        moving bar instead of "0%"."""
        return not self.steps_total or self.steps_total <= 1

    @property
    def percent(self) -> int:
        if self.state == self.DONE:
            return 100
        if self.is_indeterminate:
            return 0
        return max(0, min(100, round((self.steps_done / self.steps_total) * 100)))

    @property
    def is_terminal(self) -> bool:
        return self.state in self.TERMINAL_STATES

    @property
    def is_running(self) -> bool:
        return self.state in (self.QUEUED, self.RUNNING)

    # --- Transitions -----------------------------------------------------
    def mark_running(self, step: str = "", *, steps_total: int | None = None):
        fields = ["state", "current_step", "attempts", "updated_at"]
        self.state = self.RUNNING
        if step:
            self.current_step = str(step)
        if steps_total is not None:
            self.steps_total = steps_total
            fields.append("steps_total")
        if self.started_at is None:
            self.started_at = timezone.now()
            fields.append("started_at")
        self.attempts += 1
        self.save(update_fields=fields)

    def advance(self, step: str = "", *, done_delta: int = 1):
        """Record one completed step. Used by every multi-step path."""
        self.refresh_from_db(fields=["steps_done", "steps_total"])
        self.steps_done = min(self.steps_total, self.steps_done + done_delta)
        self.current_step = str(step) if step else self.current_step
        self.state = self.RUNNING
        self.save(update_fields=["steps_done", "current_step", "state", "updated_at"])

    def set_step(self, step: str):
        self.current_step = str(step)
        self.save(update_fields=["current_step", "updated_at"])

    def mark_done(self, step: str = ""):
        self.state = self.DONE
        self.steps_done = self.steps_total
        if step:
            self.current_step = str(step)
        self.finished_at = timezone.now()
        self.save(
            update_fields=[
                "state", "steps_done", "current_step", "finished_at", "updated_at",
            ]
        )

    def mark_failed(self, message: str):
        self.state = self.FAILED
        self.error_message = str(message)[:2000]
        self.finished_at = timezone.now()
        self.save(update_fields=["state", "error_message", "finished_at", "updated_at"])

    # --- Construction ----------------------------------------------------
    @classmethod
    def start_for(cls, profile, kind: str, target, *, steps_total: int = 1, step: str = ""):
        """Create a queued task pointing at `target`, owned by `profile`.

        Any earlier non-terminal task for the same target and kind is canceled,
        so a re-run never leaves two live progress bars on one object.
        """
        content_type = ContentType.objects.get_for_model(target.__class__)
        cls.objects.filter(
            content_type=content_type,
            object_id=target.pk,
            kind=kind,
            state__in=[cls.QUEUED, cls.RUNNING],
        ).update(state=cls.CANCELED, finished_at=timezone.now())
        return cls.objects.create(
            user=profile.user,
            profile=profile,
            kind=kind,
            target=target,
            steps_total=max(1, steps_total),
            current_step=str(step),
        )

    @classmethod
    def latest_for(cls, target, kind: str | None = None):
        content_type = ContentType.objects.get_for_model(target.__class__)
        qs = cls.objects.filter(content_type=content_type, object_id=target.pk)
        if kind:
            qs = qs.filter(kind=kind)
        return qs.first()
