"""
Django settings for the easy-apply project.
"""

import sys
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-dev-only-change-me-in-production-!!!",
)

DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS", default="", cast=Csv()
)


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "widget_tweaks",
    # Local apps
    "accounts",
    "core",
    "skills",
    "languages",
    "experience",
    "education",
    "jobs",
    "resume",
    "preferences",
    "legal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Resolves request.profile — every content query is scoped to it.
    "core.middleware.ActiveProfileMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_context",
                "core.context_processors.active_profile",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database

# SQLite runs with WAL + a busy timeout because the Celery worker (see
# config/celery.py) writes to the same file as the web process. Postgres is the
# recommended production database now that there are two writer processes.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # WAL itself is set by the connection_created receiver in core/apps.py —
        # Django 5.0's SQLite backend has no `init_command` option.
        "OPTIONS": {"timeout": 20},
    }
}


# Custom user model

AUTH_USER_MODEL = "accounts.User"


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("fr", "Français"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = config("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# The manifest storage needs `collectstatic` to have run, which is right for
# production but would make `manage.py test` depend on a build step.
_TESTING = "test" in sys.argv or "pytest" in sys.modules
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if _TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Media files (user uploads: avatars, ...)

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Authentication redirects

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"


# Email (defaults to console backend for local development)

EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="Easy Apply <noreply@easy-apply.app>"
)

# Password reset links expire after 3 days (in seconds)
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3

SITE_NAME = "Easy Apply"

# DeepSeek API (used by the `jobs` app to structure job postings into
# relational data). Leave DEEPSEEK_API_KEY empty to disable AI analysis —
# the app will show a clear error instead of crashing.
DEEPSEEK_API_KEY = config("DEEPSEEK_API_KEY", default="")
DEEPSEEK_API_BASE = config("DEEPSEEK_API_BASE", default="https://api.deepseek.com")
DEEPSEEK_MODEL = config("DEEPSEEK_MODEL", default="deepseek-v4-flash")
DEEPSEEK_TIMEOUT = config("DEEPSEEK_TIMEOUT", default=60, cast=int)

# Job-post URL fetcher
JOB_FETCH_TIMEOUT = config("JOB_FETCH_TIMEOUT", default=15, cast=int)
JOB_FETCH_MAX_BYTES = config("JOB_FETCH_MAX_BYTES", default=2_000_000, cast=int)

# Resume upload (jobs -> profile auto-fill)
RESUME_MAX_UPLOAD_BYTES = config("RESUME_MAX_UPLOAD_BYTES", default=8_000_000, cast=int)

# Tailored-resume PDF export ("letter" or "a4")
RESUME_PDF_PAGE_SIZE = config("RESUME_PDF_PAGE_SIZE", default="letter")

# Security hardening toggles (enabled automatically when DEBUG is off)
if not DEBUG:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True


# Celery — every AI call runs off the request cycle (see config/celery.py and
# the *_tasks.py modules). CELERY_TASK_ALWAYS_EAGER defaults to True in DEBUG so
# the app (and the test suite) runs with no broker and no worker.
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=DEBUG, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_TIME_LIMIT = config("CELERY_TASK_TIME_LIMIT", default=600, cast=int)
CELERY_TASK_SOFT_TIME_LIMIT = config("CELERY_TASK_SOFT_TIME_LIMIT", default=540, cast=int)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Fail fast when the broker is unreachable rather than retrying for ~20s while
# a user waits on the page. core.tasks.dispatch turns the resulting error into
# a failed AITask with a Retry button; see the NoWorkerTests in jobs/tests.py.
CELERY_BROKER_CONNECTION_MAX_RETRIES = config(
    "CELERY_BROKER_CONNECTION_MAX_RETRIES", default=1, cast=int
)
CELERY_BROKER_TRANSPORT_OPTIONS = {"max_retries": 1, "socket_connect_timeout": 3}
CELERY_RESULT_BACKEND_ALWAYS_RETRY = False
CELERY_RESULT_BACKEND_MAX_RETRIES = 1
CELERY_REDIS_SOCKET_CONNECT_TIMEOUT = 3
CELERY_REDIS_SOCKET_TIMEOUT = 10

# How long a running AITask may go without an update before the worker's
# startup sweep marks it failed (seconds).
AI_TASK_STALE_AFTER = config("AI_TASK_STALE_AFTER", default=3600, cast=int)
# Terminal AITask rows older than this many days are pruned by
# `manage.py prune_ai_tasks`.
AI_TASK_RETENTION_DAYS = config("AI_TASK_RETENTION_DAYS", default=30, cast=int)


# Legal entity details rendered into the pages served by the `legal` app.
# TODO: replace every placeholder below before going to production.
LEGAL_ENTITY = {
    "name": config("LEGAL_NAME", default="TODO: Registered company name"),
    "address": config("LEGAL_ADDRESS", default="TODO: Registered address"),
    "email": config("LEGAL_EMAIL", default="TODO: contact@example.com"),
    "jurisdiction": config("LEGAL_JURISDICTION", default="TODO: Québec, Canada"),
    "registration": config("LEGAL_REGISTRATION", default="TODO: Company registration number"),
    "director": config("LEGAL_DIRECTOR", default="TODO: Publication director"),
    "host_name": config("LEGAL_HOST_NAME", default="TODO: Hosting provider"),
    "host_address": config("LEGAL_HOST_ADDRESS", default="TODO: Hosting provider address"),
    "dpo_email": config("LEGAL_DPO_EMAIL", default="TODO: privacy@example.com"),
}
