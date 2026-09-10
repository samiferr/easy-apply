# Re-exported so Celery's app is registered whenever Django loads the project.
from .celery import app as celery_app

__all__ = ("celery_app",)
