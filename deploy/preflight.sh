#!/usr/bin/env bash
# One-time VPS readiness check for Easy Apply, targeting Ubuntu 24.04.
# Confirms every system package deploy/deploy.sh needs is present, and
# installs whatever is missing. Meant to be run by hand once on a fresh VPS
# before the first GitHub Actions deploy, so failures show up here instead
# of mid-deploy in CI.
#
# Usage (as root, or via sudo):
#   sudo bash deploy/preflight.sh                  # check/install core packages only
#   sudo bash deploy/preflight.sh --with-postgres  # also run PostgreSQL on this box:
#                                                  # install it, create the easy_apply
#                                                  # role + database, print DATABASE_URL
#
# Safe to re-run any time - every check is idempotent and only touches
# what's missing.
set -euo pipefail

REQUIRED_PACKAGES=(
  git
  curl
  python3
  python3-venv
  python3-pip
  python3-dev
  build-essential
  # msgfmt, for manage.py compilemessages (French catalogue)
  gettext
  nginx
  certbot
  python3-certbot-nginx
  # Celery broker - every AI call is queued through it
  redis-server
  # pg_dump, for deploy.sh's pre-migration backup
  postgresql-client
)

DB_NAME="easy_apply"
DB_USER="easy_apply"

WITH_POSTGRES=false
for arg in "$@"; do
  case "$arg" in
    --with-postgres)
      WITH_POSTGRES=true
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--with-postgres]" >&2
      exit 1
      ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (or via sudo)." >&2
  exit 1
fi

echo "==> Checking OS"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "Detected: ${PRETTY_NAME:-unknown}"
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "WARNING: this script targets Ubuntu 24.04; you're on ${PRETTY_NAME:-an unrecognized OS}." >&2
    echo "         Continuing anyway, but package names/behavior may differ." >&2
  fi
else
  echo "WARNING: /etc/os-release not found; cannot confirm this is Ubuntu 24.04." >&2
fi

if $WITH_POSTGRES; then
  REQUIRED_PACKAGES+=(postgresql postgresql-contrib openssl)
fi

echo "==> Refreshing package index"
apt-get update -y

echo "==> Checking required packages"
MISSING=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    echo "  [ok]      $pkg"
  else
    echo "  [missing] $pkg"
    MISSING+=("$pkg")
  fi
done

if [ "${#MISSING[@]}" -gt 0 ]; then
  echo "==> Installing missing packages: ${MISSING[*]}"
  apt-get install -y "${MISSING[@]}"
else
  echo "==> All required packages already installed"
fi

echo "==> Verifying installed versions"
python3 --version
git --version
nginx -v
certbot --version
redis-server --version

echo "==> Checking Redis"
systemctl enable --now redis-server
redis-cli ping | grep -q PONG \
  && echo "redis: responding" \
  || { echo "redis-server is installed but not answering PING" >&2; exit 1; }

if $WITH_POSTGRES; then
  echo "==> Checking PostgreSQL"
  psql --version
  systemctl enable --now postgresql
  if systemctl is-active --quiet postgresql; then
    echo "postgresql service: active"
  else
    echo "postgresql service failed to start" >&2
    exit 1
  fi

  echo "==> Creating the ${DB_USER} role and ${DB_NAME} database (if missing)"
  DB_PASSWORD=""
  if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'" | grep -q 1; then
    echo "Role ${DB_USER} already exists - left unchanged (its password is not reset)."
  else
    # Hex, so the password never needs URL-encoding inside DATABASE_URL. Sent
    # on stdin rather than the command line, which other users can see.
    DB_PASSWORD="$(openssl rand -hex 24)"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
SQL
    echo "Created role ${DB_USER}."
  fi
  if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
    echo "Database ${DB_NAME} already exists - left unchanged."
  else
    sudo -u postgres createdb --owner "$DB_USER" "$DB_NAME"
    echo "Created database ${DB_NAME}, owned by ${DB_USER}."
  fi
  if [ -n "$DB_PASSWORD" ]; then
    echo
    echo "    Save this as the DATABASE_URL GitHub Actions secret now."
    echo "    The password is not stored anywhere else, and re-running this script won't show it again:"
    echo
    echo "    postgres://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"
    echo
  fi
fi

echo "==> Checking systemd + sudo (required by deploy.sh)"
command -v systemctl >/dev/null || { echo "systemctl not found - deploy.sh requires systemd." >&2; exit 1; }
command -v sudo >/dev/null || echo "WARNING: sudo not found; the deploy user needs passwordless sudo (see deploy/README.md)." >&2

echo "==> Checking gunicorn port 8005 is free (informational)"
if ss -tln | grep -q ':8005 '; then
  if systemctl is-active --quiet gunicorn-easy-apply 2>/dev/null; then
    echo "Port 8005 is held by gunicorn-easy-apply (a previous deploy) - fine."
  else
    echo "WARNING: something other than easy-apply already listens on 127.0.0.1:8005." >&2
    echo "         Change GUNICORN_PORT in deploy/deploy.sh and .github/workflows/deploy.yml." >&2
  fi
else
  echo "Port 8005 is free."
fi

echo "==> Checking firewall (informational only - not modified by this script)"
if command -v ufw >/dev/null 2>&1; then
  if ufw status | grep -q "Status: active"; then
    echo "ufw is active. Current rules:"
    ufw status
    echo "Make sure OpenSSH (or your custom SSH port) and 'Nginx Full' (ports 80/443) are allowed, e.g.:"
    echo "  ufw allow OpenSSH"
    echo "  ufw allow 'Nginx Full'"
  else
    echo "ufw is installed but inactive - no firewall rules to check."
  fi
else
  echo "ufw not installed - skipping firewall check."
fi

echo
echo "==> Preflight complete. This VPS is ready for deploy/deploy.sh."
