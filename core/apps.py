from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def set_sqlite_pragmas(sender, connection, **kwargs):
    """Put SQLite in WAL mode with a busy timeout.

    The Celery worker writes to the same database file as the web process, so
    without WAL a long-running write blocks readers outright. Django 5.0 has no
    `init_command` OPTION for SQLite, hence the signal.
    """
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=20000;")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
