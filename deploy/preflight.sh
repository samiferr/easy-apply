#!/usr/bin/env bash
# One-time VPS readiness check for Easy Apply, targeting Ubuntu 24.04.
# Confirms every system package deploy/deploy.sh needs is present, and
# installs whatever is missing. Meant to be run by hand once on a fresh VPS
# before the first GitHub Actions deploy, so failures show up here instead
# of mid-deploy in CI.
#
# Usage (as root, or via sudo):
#   sudo bash deploy/preflight.sh
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
)

if [ "$#" -gt 0 ]; then
  echo "Usage: $0" >&2
  exit 1
fi

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
