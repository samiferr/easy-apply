"""Shared Celery helpers used by every AI task path."""

import functools
import logging

from celery.exceptions import SoftTimeLimitExceeded
from django.utils.translation import gettext as _

from core.ai import AIConfigError, AIServiceError
from core.models import AITask

logger = logging.getLogger(__name__)

#: Only transient failures are worth retrying. AIConfigError (no API key) and a
#: malformed-JSON AIServiceError are deterministic — retrying just burns quota.
RETRYABLE_HINTS = ("timed out", "rate-limiting", "Couldn't reach", "HTTP 5")


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, AIConfigError):
        return False
    if isinstance(exc, AIServiceError):
        return any(hint in str(exc) for hint in RETRYABLE_HINTS)
    return False


def get_task(task_id):
    return AITask.objects.filter(pk=task_id).first()


def fail_task(task: AITask | None, message: str):
    if task is not None:
        task.mark_failed(message)


def guard(fn):
    """Wrap a task body so soft time limits surface as a clean user message."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SoftTimeLimitExceeded:
            raise AIServiceError(
                _("This took too long and was stopped. Please try again.")
            )

    return wrapper
