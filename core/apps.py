from django.apps import AppConfig
from django.conf import settings
from django.db.backends.signals import connection_created
from django.dispatch import receiver
from django.utils.autoreload import autoreload_started


@receiver(connection_created)
def set_sqlite_pragmas(sender, connection, **kwargs):
    """Put SQLite in WAL mode with a busy timeout.

    The Celery worker writes to the same database file as the web process, so
    without WAL a long-running write blocks readers outright. This predates
    the SQLite `init_command` OPTION added in Django 5.1; the signal does the
    same job and applies to any SQLite connection, however it's configured.
    """
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=20000;")


@receiver(autoreload_started)
def watch_prompt_files(sender, **kwargs):
    """Restart the dev server when a prompt file changes.

    Prompts are read once, by the module that owns them, so without this an
    edit would be ignored until someone remembered to restart — unlike editing
    the same text in a .py file, which the reloader has always picked up.
    """
    sender.watch_dir(settings.PROMPTS_DIR, "**/*.txt")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
