#!/usr/bin/env bash
# Idempotent deploy/update script for Easy Apply on Ubuntu 24.04.
# Runs as root on the target VPS from within the checked-out repo
# (CWD = /var/www/easy-apply, already at the desired git commit).
set -euo pipefail

APP_DIR="/var/www/easy-apply"
GUNICORN_PORT="8005"
SITE_NAME="easy-apply"

: "${DOMAIN:?DOMAIN must be set}"
: "${DJANGO_SECRET_KEY:?DJANGO_SECRET_KEY must be set}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL must be set}"
: "${DEPLOY_USER:?DEPLOY_USER must be set}"
: "${DATABASE_URL:?DATABASE_URL must be set}"
: "${INCLUDE_WWW:=true}"

# Accept any common spelling (False, "no", "0", stray whitespace from a pasted
# secret), and refuse anything else rather than silently guessing.
INCLUDE_WWW_NORMALIZED="$(printf '%s' "$INCLUDE_WWW" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
DOMAINS=("$DOMAIN")
case "$INCLUDE_WWW_NORMALIZED" in
    true|1|yes|on) DOMAINS+=("www.${DOMAIN}") ;;
    false|0|no|off) ;;
    *)
        echo "INCLUDE_WWW must be true or false (got '${INCLUDE_WWW}')." >&2
        exit 1
        ;;
esac
echo "==> Serving: ${DOMAINS[*]}"
SERVER_NAMES="${DOMAINS[*]}"
ALLOWED_HOSTS="$(IFS=,; echo "${DOMAINS[*]}")"
CSRF_TRUSTED_ORIGINS="$(printf 'https://%s,' "${DOMAINS[@]}")"
CSRF_TRUSTED_ORIGINS="${CSRF_TRUSTED_ORIGINS%,}"

# Production runs on PostgreSQL only; config/settings.py refuses to start with
# DEBUG=False and no DATABASE_URL. Only the two schemes libpq (and so pg_dump)
# understands are accepted.
case "$DATABASE_URL" in
    postgres://*|postgresql://*) ;;
    *)
        echo "DATABASE_URL must be a PostgreSQL URL (postgres://USER:PASSWORD@HOST:PORT/NAME)." >&2
        exit 1
        ;;
esac

cd "$APP_DIR"

echo "==> Installing system packages"
apt-get update -y
# gettext provides msgfmt for compilemessages; redis-server is the Celery
# broker every AI call is queued through; postgresql-client provides the
# pg_dump used for the pre-migration backup below. The PostgreSQL server itself
# is not installed here: it's either a managed instance or set up once with
# `deploy/preflight.sh --with-postgres` (see deploy/README.md).
apt-get install -y python3-venv python3-pip python3-dev build-essential \
    gettext nginx certbot python3-certbot-nginx redis-server postgresql-client
systemctl enable --now redis-server

echo "==> Python virtualenv"
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Writing environment file"
# Optional settings are only written when set, so config/settings.py's own
# defaults apply otherwise (an empty value would override them, and break the
# int/bool casts).
OPTIONAL_VARS=(
    TIME_ZONE
    DEEPSEEK_API_KEY DEEPSEEK_API_BASE DEEPSEEK_MODEL DEEPSEEK_TIMEOUT
    EMAIL_BACKEND EMAIL_HOST EMAIL_PORT EMAIL_HOST_USER EMAIL_HOST_PASSWORD
    EMAIL_USE_TLS DEFAULT_FROM_EMAIL
    LEGAL_NAME LEGAL_ADDRESS LEGAL_EMAIL LEGAL_JURISDICTION LEGAL_REGISTRATION
    LEGAL_DIRECTOR LEGAL_HOST_NAME LEGAL_HOST_ADDRESS LEGAL_DPO_EMAIL
)
{
    echo "SECRET_KEY=${DJANGO_SECRET_KEY}"
    echo "DEBUG=False"
    echo "DATABASE_URL=${DATABASE_URL}"
    echo "ALLOWED_HOSTS=${ALLOWED_HOSTS}"
    echo "CSRF_TRUSTED_ORIGINS=${CSRF_TRUSTED_ORIGINS}"
    # nginx already redirects HTTP to HTTPS, and Django sees plain HTTP from
    # it, so a Django-side redirect would loop.
    echo "SECURE_SSL_REDIRECT=False"
    # nginx overwrites X-Forwarded-For with the real client address (see
    # nginx-easy-apply.conf), which is what makes trusting it safe.
    echo "STAFF_PORTAL_TRUST_X_FORWARDED_FOR=True"
    echo "CELERY_BROKER_URL=redis://127.0.0.1:6379/0"
    echo "CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1"
    echo "CELERY_TASK_ALWAYS_EAGER=False"
    for name in "${OPTIONAL_VARS[@]}"; do
        if [ -n "${!name:-}" ]; then
            echo "${name}=${!name}"
        fi
    done
} > "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "==> Fixing ownership"
mkdir -p "$APP_DIR/media/avatars" "$APP_DIR/staticfiles" "$APP_DIR/backups"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
chmod 700 "$APP_DIR/backups"

# Run as the same user as gunicorn and the Celery worker, so nothing in the
# checkout ends up owned by root.
manage() {
    sudo -u "$DEPLOY_USER" "$APP_DIR/venv/bin/python" "$APP_DIR/manage.py" "$@"
}

echo "==> Testing database connection"
manage shell -c "
from django.db import connection
connection.ensure_connection()
print(f'Connected to PostgreSQL {connection.pg_version // 10000}.')
"

echo "==> Backing up the database"
# pg_dump (custom format, restore with pg_restore) before every migrate; the
# last 10 dumps are kept. The credentials reach pg_dump through PG*
# environment variables rather than its command line, where any local user
# could read them from the process list. A failed dump (e.g. the server is a
# newer major version than this box's pg_dump) is reported but doesn't block
# the deploy.
BACKUP="$APP_DIR/backups/db-$(date -u +%Y%m%dT%H%M%SZ).dump"
if "$APP_DIR/venv/bin/python" - "$BACKUP" <<'PY'
import os
import subprocess
import sys

import dj_database_url

db = dj_database_url.parse(os.environ["DATABASE_URL"])
env = dict(os.environ)
env.pop("DATABASE_URL")
for var, value in {
    "PGHOST": db.get("HOST"),
    "PGPORT": db.get("PORT"),
    "PGUSER": db.get("USER"),
    "PGPASSWORD": db.get("PASSWORD"),
    "PGDATABASE": db.get("NAME"),
    "PGSSLMODE": db.get("OPTIONS", {}).get("sslmode"),
}.items():
    if value:
        env[var] = str(value)
subprocess.run(
    ["pg_dump", "--format=custom", "--no-owner", "--file", sys.argv[1]],
    env=env,
    check=True,
)
PY
then
    chown "$DEPLOY_USER:$DEPLOY_USER" "$BACKUP"
    chmod 600 "$BACKUP"
    echo "Saved $BACKUP"
    find "$APP_DIR/backups" -maxdepth 1 -name 'db-*.dump' -printf '%T@ %p\n' \
        | sort -rn | tail -n +11 | cut -d' ' -f2- | xargs -r rm -f
else
    rm -f "$BACKUP"
    echo "WARNING: pg_dump failed; migrating WITHOUT a fresh backup." >&2
fi

echo "==> Django management commands"
manage migrate --noinput
# Starter plans, flags, and a subscription for every account. Idempotent:
# only fills gaps and never rewrites an existing plan.
manage seed_saas --backfill
# --ignore=venv keeps this to this project's catalogue rather than every .po
# shipped by Django and the other dependencies.
manage compilemessages --locale fr --ignore=venv
manage collectstatic --clear --noinput

echo "==> Opening static files and avatars to nginx"
# nginx (www-data) only needs read+traverse access to static files and
# avatars. Uploaded resumes under media/resumes/ are never served by nginx.
chmod -R go+rX "$APP_DIR/staticfiles" "$APP_DIR/media/avatars"
chmod go+rX "$APP_DIR" "$APP_DIR/media"
# ...and nothing else holding user data is readable by other local accounts.
chmod -R go-rwx "$APP_DIR/backups"
if [ -d "$APP_DIR/media/resumes" ]; then
    chmod -R go-rwx "$APP_DIR/media/resumes"
fi

echo "==> Installing systemd services"
for unit in gunicorn-easy-apply.service celery-easy-apply.service \
            easy-apply-housekeeping.service easy-apply-housekeeping.timer; do
    sed -e "s/__DEPLOY_USER__/${DEPLOY_USER}/g" \
        -e "s/__GUNICORN_PORT__/${GUNICORN_PORT}/g" \
        "$APP_DIR/deploy/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable gunicorn-easy-apply celery-easy-apply easy-apply-housekeeping.timer
systemctl restart gunicorn-easy-apply celery-easy-apply
systemctl start easy-apply-housekeeping.timer

echo "==> TLS certificate"
# ACME HTTP-01 challenges are served from a plain directory (certbot
# --webroot) rather than through certbot's --nginx plugin, the same as the
# Wise Store pipeline: the plugin's live config rewriting has been seen to
# silently not take effect. The final nginx config keeps serving this path, so
# renewals by certbot's own systemd timer keep working too.
ACME_WEBROOT="/var/www/certbot"
mkdir -p "$ACME_WEBROOT"

CERTBOT_DOMAINS=()
for d in "${DOMAINS[@]}"; do
    CERTBOT_DOMAINS+=(-d "$d")
done

if [ ! -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    # Bootstrap a plain HTTP vhost so the challenge path is served before the
    # real, certificate-referencing config can pass `nginx -t`.
    cat > "/etc/nginx/sites-available/${SITE_NAME}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAMES};

    location /.well-known/acme-challenge/ {
        root ${ACME_WEBROOT};
    }

    location / { return 200 "ok"; }
}
EOF
    ln -sf "/etc/nginx/sites-available/${SITE_NAME}" "/etc/nginx/sites-enabled/${SITE_NAME}"
    nginx -t
    systemctl reload nginx

    certbot certonly --webroot -w "$ACME_WEBROOT" "${CERTBOT_DOMAINS[@]}" \
        --cert-name "$DOMAIN" --non-interactive --agree-tos -m "$LETSENCRYPT_EMAIL"
else
    # --expand adds www.<DOMAIN> if INCLUDE_WWW was switched on after the
    # first issuance; otherwise certbot keeps the existing, unexpired cert.
    certbot certonly --webroot -w "$ACME_WEBROOT" "${CERTBOT_DOMAINS[@]}" \
        --cert-name "$DOMAIN" --expand --keep-until-expiring \
        --non-interactive --agree-tos -m "$LETSENCRYPT_EMAIL"
fi

echo "==> Installing nginx site"
sed -e "s/__DOMAIN__/${DOMAIN}/g" \
    -e "s/__SERVER_NAMES__/${SERVER_NAMES}/g" \
    -e "s/__GUNICORN_PORT__/${GUNICORN_PORT}/g" \
    "$APP_DIR/deploy/nginx-easy-apply.conf" > "/etc/nginx/sites-available/${SITE_NAME}"
ln -sf "/etc/nginx/sites-available/${SITE_NAME}" "/etc/nginx/sites-enabled/${SITE_NAME}"
nginx -t
systemctl reload nginx

echo "==> Deploy complete: https://${DOMAIN}/"
