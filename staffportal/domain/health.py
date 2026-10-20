"""Production-readiness and liveness checks, run on demand from the portal.

Two kinds of question, answered on one screen because an operator asks them at
the same moment: *is it up* (database, broker, workers) and *is it configured
like production* (DEBUG, secret key, hosts, TLS, email, legal placeholders).
The second kind is what actually bites — nobody forgets to start the database,
and everybody forgets `DEBUG=False` once.

Every check is defensive: a check that raises is reported as a failed check,
never as a 500 on the page you opened to find out what is broken.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

OK = "ok"
WARN = "warn"
FAIL = "fail"

_INSECURE_KEY_PREFIX = "django-insecure"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    group: str = "Runtime"

    @property
    def is_ok(self) -> bool:
        return self.status == OK


def _safe(fn, name: str, group: str) -> Check:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover — defensive
        return Check(name, FAIL, f"Check raised: {exc.__class__.__name__}: {exc}", group)


# --- Liveness --------------------------------------------------------------
def _database() -> Check:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    engine = connection.settings_dict["ENGINE"].rsplit(".", 1)[-1]
    if engine == "sqlite3" and not settings.DEBUG:
        return Check(
            "Database",
            WARN,
            "Reachable, but running SQLite with a web process and a Celery worker "
            "writing the same file. Move to PostgreSQL for production.",
            "Liveness",
        )
    return Check("Database", OK, f"Reachable ({engine}).", "Liveness")


def _migrations() -> Check:
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)
    if plan:
        names = ", ".join(f"{m.app_label}.{m.name}" for m, _backwards in plan[:5])
        return Check(
            "Migrations", FAIL, f"{len(plan)} unapplied: {names}", "Liveness"
        )
    return Check("Migrations", OK, "Everything applied.", "Liveness")


def _celery() -> Check:
    if settings.CELERY_TASK_ALWAYS_EAGER:
        status = WARN if not settings.DEBUG else OK
        return Check(
            "Celery workers",
            status,
            "Tasks run inline (CELERY_TASK_ALWAYS_EAGER). Correct for local work "
            "and tests; in production it blocks the request on every AI call.",
            "Liveness",
        )
    from config.celery import app

    replies = app.control.ping(timeout=1.0) or []
    if not replies:
        return Check(
            "Celery workers",
            FAIL,
            "No worker answered within 1s. Queued AI work will sit unprocessed.",
            "Liveness",
        )
    names = ", ".join(sorted(name for reply in replies for name in reply))
    return Check("Celery workers", OK, f"{len(replies)} responding: {names}", "Liveness")


def _queue() -> Check:
    from core.models import AITask

    stale_after = timedelta(seconds=settings.AI_TASK_STALE_AFTER)
    stuck = AITask.objects.filter(
        state=AITask.RUNNING, updated_at__lt=timezone.now() - stale_after
    ).count()
    waiting = AITask.objects.filter(state=AITask.QUEUED).count()
    if stuck:
        return Check(
            "AI queue",
            WARN,
            f"{stuck} task(s) running with no update for over "
            f"{settings.AI_TASK_STALE_AFTER}s. Run `manage.py sweep_stuck_ai_tasks`.",
            "Liveness",
        )
    return Check("AI queue", OK, f"{waiting} queued, nothing stuck.", "Liveness")


# --- Configuration ---------------------------------------------------------
def _debug() -> Check:
    if settings.DEBUG:
        return Check(
            "DEBUG",
            WARN if _looks_local() else FAIL,
            "DEBUG is on. In production it leaks settings, SQL and stack traces "
            "to anyone who triggers an error.",
            "Configuration",
        )
    return Check("DEBUG", OK, "Off.", "Configuration")


def _looks_local() -> bool:
    hosts = set(settings.ALLOWED_HOSTS)
    return not hosts or hosts <= {"localhost", "127.0.0.1", "[::1]", "testserver"}


def _secret_key() -> Check:
    key = settings.SECRET_KEY or ""
    if key.startswith(_INSECURE_KEY_PREFIX) or len(key) < 40:
        return Check(
            "SECRET_KEY",
            FAIL if not settings.DEBUG else WARN,
            "Still the development default (or too short). Sessions and password "
            "reset links are forgeable until it is replaced.",
            "Configuration",
        )
    return Check("SECRET_KEY", OK, "Set to a non-default value.", "Configuration")


def _hosts() -> Check:
    if _looks_local() and not settings.DEBUG:
        return Check(
            "ALLOWED_HOSTS",
            FAIL,
            "Only local hostnames are allowed — the site will reject real traffic.",
            "Configuration",
        )
    return Check(
        "ALLOWED_HOSTS", OK, ", ".join(settings.ALLOWED_HOSTS) or "(empty, DEBUG only)",
        "Configuration",
    )


def _https() -> Check:
    if settings.DEBUG:
        return Check("HTTPS", OK, "Not enforced in development.", "Configuration")
    missing = [
        name
        for name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE")
        if not getattr(settings, name, False)
    ]
    if missing:
        return Check("HTTPS", FAIL, f"Missing: {', '.join(missing)}.", "Configuration")
    if not getattr(settings, "SECURE_SSL_REDIRECT", False):
        return Check(
            "HTTPS",
            WARN,
            "Cookies are secure but SECURE_SSL_REDIRECT is off — fine behind a "
            "proxy that already redirects, a hole if not.",
            "Configuration",
        )
    return Check("HTTPS", OK, "Cookies secure and HTTP redirected.", "Configuration")


def _email() -> Check:
    backend = settings.EMAIL_BACKEND.rsplit(".", 1)[-1]
    if "console" in settings.EMAIL_BACKEND or "locmem" in settings.EMAIL_BACKEND:
        return Check(
            "Email",
            WARN if settings.DEBUG else FAIL,
            f"{backend}: password-reset emails are not delivered to anyone.",
            "Configuration",
        )
    if not settings.EMAIL_HOST:
        return Check("Email", FAIL, "No EMAIL_HOST configured.", "Configuration")
    return Check("Email", OK, f"{backend} via {settings.EMAIL_HOST}.", "Configuration")


def _ai_provider() -> Check:
    if not settings.DEEPSEEK_API_KEY:
        return Check(
            "AI provider",
            WARN,
            "DEEPSEEK_API_KEY is empty. Every AI feature refuses with a clear "
            "message instead of running.",
            "Configuration",
        )
    return Check(
        "AI provider", OK, f"{settings.DEEPSEEK_MODEL} at {settings.DEEPSEEK_API_BASE}.",
        "Configuration",
    )


def _legal() -> Check:
    placeholders = [k for k, v in settings.LEGAL_ENTITY.items() if str(v).startswith("TODO")]
    if placeholders:
        return Check(
            "Legal pages",
            WARN,
            f"{len(placeholders)} placeholder(s) still published: "
            f"{', '.join(sorted(placeholders))}.",
            "Configuration",
        )
    return Check("Legal pages", OK, "Entity details filled in.", "Configuration")


def _billing_setup() -> Check:
    from ..models import Plan

    if not Plan.objects.exists():
        return Check(
            "Plans",
            WARN,
            "No plans defined — every account is effectively unlimited. "
            "Run `manage.py seed_saas` or add one.",
            "Configuration",
        )
    if not Plan.objects.filter(is_default=True, is_active=True).exists():
        return Check(
            "Plans",
            FAIL,
            "No active default plan: new sign-ups get no subscription at all.",
            "Configuration",
        )
    return Check(
        "Plans", OK, f"{Plan.objects.filter(is_active=True).count()} active.", "Configuration"
    )


def _static_files() -> Check:
    if settings.DEBUG:
        return Check("Static files", OK, "Served from source in DEBUG.", "Configuration")
    manifest = settings.STATIC_ROOT / "staticfiles.json"
    if not manifest.exists():
        return Check(
            "Static files",
            FAIL,
            "No manifest at STATIC_ROOT — `collectstatic` has not been run, so "
            "every hashed asset URL will 500.",
            "Configuration",
        )
    return Check("Static files", OK, "Manifest present.", "Configuration")


CHECKS = (
    (_database, "Database", "Liveness"),
    (_migrations, "Migrations", "Liveness"),
    (_celery, "Celery workers", "Liveness"),
    (_queue, "AI queue", "Liveness"),
    (_debug, "DEBUG", "Configuration"),
    (_secret_key, "SECRET_KEY", "Configuration"),
    (_hosts, "ALLOWED_HOSTS", "Configuration"),
    (_https, "HTTPS", "Configuration"),
    (_email, "Email", "Configuration"),
    (_ai_provider, "AI provider", "Configuration"),
    (_billing_setup, "Plans", "Configuration"),
    (_legal, "Legal pages", "Configuration"),
    (_static_files, "Static files", "Configuration"),
)


def run_checks() -> list[Check]:
    return [_safe(fn, name, group) for fn, name, group in CHECKS]


def summarize(checks: list[Check]) -> dict:
    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    return {
        "status": FAIL if failed else (WARN if warned else OK),
        "failed": len(failed),
        "warned": len(warned),
        "passed": len(checks) - len(failed) - len(warned),
        "total": len(checks),
    }
