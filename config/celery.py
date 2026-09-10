"""Celery application for Easy Apply.

Every AI call — resume analysis, job analysis, matching analysis and
tailored-resume generation — runs through a task defined in one of the
`*/tasks.py` modules rather than in a request. See core/models.py::AITask for
the shared progress record all four paths report through.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("easy_apply")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover - operational helper
    print(f"Request: {self.request!r}")
