# Deploying Easy Apply to the VPS

Production runs on an Ubuntu 24.04 VPS behind nginx + Let's Encrypt, with
gunicorn serving Django, a Celery worker running every AI call, and Redis as
the broker. It uses the same pipeline as Wise Store Canada (SSH + systemd +
nginx + certbot `--webroot`), with one difference: **the server's IP address
and domain name are not committed**. They come from GitHub Actions secrets
(or variables), so the same files work on any box.

`.github/workflows/deploy.yml` is the pipeline: it SSHes into the VPS and runs
`deploy/deploy.sh` on every push to `main`, or on demand via **Run workflow**.

| Piece | Where |
|---|---|
| App checkout | `/var/www/easy-apply` |
| Web process | `gunicorn-easy-apply.service`, bound to `127.0.0.1:8005` |
| AI worker | `celery-easy-apply.service` (`celery -A config worker --concurrency=2`) |
| Broker | `redis-server`, databases `0` (broker) and `1` (results) |
| Retention jobs | `easy-apply-housekeeping.timer`, daily: `prune_ai_tasks`, `prune_audit_log` |
| Reverse proxy | `/etc/nginx/sites-available/easy-apply` |
| Database | SQLite, `/var/www/easy-apply/db.sqlite3`, snapshotted to `backups/` before each migrate |

Port `8005` sits next to Wise Store (`8004`) and DCMS7 (`8003`), so all three
can share a VPS.

## 1. One-time setup

### 1.1 Prepare the VPS

SSH in and run the preflight script. It checks the OS and installs anything
`deploy.sh` needs that's missing (`python3-venv`, `gettext`, `nginx`,
`certbot`, `redis-server`, ...). Safe to re-run.

```bash
git clone --depth 1 https://github.com/samiferr/easy-apply /tmp/ea-preflight
sudo bash /tmp/ea-preflight/deploy/preflight.sh
rm -rf /tmp/ea-preflight
```

(If the repo is private, run it from an existing checkout instead:
`sudo bash /var/www/easy-apply/deploy/preflight.sh`.)

### 1.2 DNS

Point an `A` record for your domain at the VPS IP. By default the pipeline
also serves `www.<domain>`, so point that at the same IP too, or set the
`INCLUDE_WWW` variable to `false` (useful when the domain is a subdomain such
as `apply.example.com`).

Certbot fails if any name on the certificate doesn't resolve yet, so check
before the first deploy:

```bash
dig +short <domain>
dig +short www.<domain>     # unless INCLUDE_WWW=false
```

Both must print the VPS IP directly. A CDN in "proxied" mode (e.g.
Cloudflare's orange cloud) must be set to DNS-only for issuance to work.

### 1.3 The deploy user

The pipeline logs in as `VPS_USER` and runs `sudo` non-interactively, so that
user needs **passwordless sudo**:

```bash
ssh root@<vps-ip>
adduser deployuser                        # or reuse an existing deploy user
usermod -aG sudo deployuser
visudo -f /etc/sudoers.d/90-deployuser    # add: deployuser ALL=(ALL) NOPASSWD:ALL
```

Generate a dedicated key pair **without a passphrase** on your own machine
and authorize it:

```bash
ssh-keygen -t ed25519 -N "" -C "github-actions-easy-apply" -f deploy_key
ssh-copy-id -i deploy_key.pub deployuser@<vps-ip>
ssh -i deploy_key deployuser@<vps-ip> "sudo -n whoami"   # must print: root
```

The contents of `deploy_key` (the private half, including the
`-----BEGIN/END OPENSSH PRIVATE KEY-----` lines) go into the `VPS_SSH_KEY`
secret. If the VPS already has a deploy user and key for Wise Store, you can
reuse them; secrets are per repository, so you still add them here.

### 1.4 GitHub secrets and variables

Add them under **Settings → Secrets and variables → Actions**. Every setting
below except the private keys and passwords can be either a **secret** or a
**variable**; when both exist, the secret wins. Keep anything sensitive as a
secret.

**Required**

| Name | Value |
|---|---|
| `VPS_HOST` | The VPS IP address, e.g. `203.0.113.10` |
| `DOMAIN` | The public domain name, e.g. `easy-apply.app` (no `https://`, no `www.`) |
| `VPS_USER` | SSH user from § 1.3 (secret) |
| `VPS_SSH_KEY` | Private key from § 1.3 (secret) |
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` (secret) |
| `LETSENCRYPT_EMAIL` | Address for Let's Encrypt registration and expiry notices |

**Optional**

| Name | Default | Purpose |
|---|---|---|
| `VPS_SSH_PORT` | `22` | SSH port (secret) |
| `INCLUDE_WWW` | `true` | Variable. `false` to serve only `DOMAIN`, without `www.` |
| `DEEPSEEK_API_KEY` | empty (AI off) | Secret. Powers job analysis, resume import and tailored resumes |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com` | |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | |
| `DEEPSEEK_TIMEOUT` | `60` | Seconds |
| `EMAIL_BACKEND` | console (emails only logged) | `django.core.mail.backends.smtp.EmailBackend` to send password resets for real |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_USE_TLS` | empty, `587`, empty, `True` | SMTP settings |
| `EMAIL_HOST_PASSWORD` | empty | SMTP password (secret) |
| `DEFAULT_FROM_EMAIL` | `Easy Apply <noreply@easy-apply.app>` | |
| `TIME_ZONE` | `UTC` | |
| `LEGAL_NAME`, `LEGAL_ADDRESS`, `LEGAL_EMAIL`, `LEGAL_JURISDICTION`, `LEGAL_REGISTRATION`, `LEGAL_DIRECTOR`, `LEGAL_HOST_NAME`, `LEGAL_HOST_ADDRESS`, `LEGAL_DPO_EMAIL` | visible `TODO:` placeholders | The entity shown on the legal pages. Fill them all in before going live |

Anything left unset is simply not written to the server's `.env`, so the
defaults in `config/settings.py` apply. `GITHUB_TOKEN`, used to clone the
repo on the VPS, is provided by GitHub automatically.

The first step of every run, **Check required configuration**, fails with the
names of any required values that are missing.

## 2. Triggering a deploy

Every push to `main` deploys. To redeploy without new code (for example after
changing a secret, which only takes effect on the next run): **Actions →
Deploy to VPS → Run workflow**. Runs never overlap.

The run has three steps: the configuration check, **Deploy over SSH**, and
**Post-deploy diagnostics**, which prints gunicorn, Celery, Redis and nginx
status, the HTTPS response code and recent logs. Diagnostics also run when the
deploy fails.

After the first deploy, create a superuser by hand:

```bash
ssh <VPS_USER>@<vps-ip>
cd /var/www/easy-apply
venv/bin/python manage.py createsuperuser
```

Then open `/staff/operations/`: the health screen checks the rest.

## 3. What `deploy/deploy.sh` does

Running as root on the VPS, in the checked-out repo:

1. Installs system packages (`nginx`, `certbot`, `redis-server`, `gettext`,
   `python3-venv`, ...) and makes sure Redis is running.
2. Creates or updates the virtualenv at `venv/` from `requirements.txt`.
3. Writes `/var/www/easy-apply/.env` (mode `600`): `DEBUG=False`, the secret
   key, `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` built from `DOMAIN`, the
   local Redis URLs, `CELERY_TASK_ALWAYS_EAGER=False`,
   `STAFF_PORTAL_TRUST_X_FORWARDED_FOR=True`, and whichever optional settings
   are set. `SECURE_SSL_REDIRECT` stays `False` because nginx already
   redirects HTTP to HTTPS and a Django-side redirect would loop.
4. Snapshots `db.sqlite3` into `backups/` (the last 10 are kept).
5. As the deploy user: `migrate`, `seed_saas --backfill` (idempotent: starter
   plans, flags and a subscription for every account), `compilemessages`
   for French, and `collectstatic`. The compiled Tailwind CSS
   (`static/dist/output.css`) is committed, so no Node toolchain is needed.
6. Installs and restarts the gunicorn and Celery services, and enables the
   daily housekeeping timer. The worker runs `sweep_stuck_ai_tasks` on every
   start, so tasks a previous worker left running are marked failed instead
   of spinning forever.
7. Gets a Let's Encrypt certificate with `certbot certonly --webroot` the
   first time (through a temporary HTTP-only vhost), and on later runs only
   adds names if `INCLUDE_WWW` changed. Renewal is left to certbot's own
   systemd timer.
8. Renders `deploy/nginx-easy-apply.conf` with the domain and installs it.

`db.sqlite3`, `media/`, `staticfiles/` and `backups/` are untracked, so they
survive the `git reset --hard` each deploy does.

**Uploaded resumes are not public.** nginx serves `/media/avatars/` and
returns 404 for everything else under `/media/`; `media/resumes/`,
`backups/` and the database are only readable by the deploy user.

## 4. Troubleshooting

**`ssh: handshake failed: ssh: unable to authenticate`**: the VPS rejected
`VPS_SSH_KEY`. Check that the public half is in `VPS_USER`'s
`~/.ssh/authorized_keys` (`~/.ssh` must be `700`, the file `600`), that the
secret holds the full private key with its BEGIN/END lines, and that the key
has no passphrase. Test with `ssh -i deploy_key <VPS_USER>@<vps-ip> whoami`
before changing the secret.

**`sudo: a terminal is required to read the password`**: `VPS_USER` doesn't
have passwordless sudo. See § 1.3.

**AI features stay on "Queued" forever**: the worker isn't consuming.

```bash
sudo systemctl status celery-easy-apply redis-server
sudo journalctl -u celery-easy-apply -n 100
redis-cli ping
```

**Certbot fails with `DNS problem: NXDOMAIN`**: one of the names isn't in DNS
yet. Add the record (or set `INCLUDE_WWW=false`) and re-run the workflow.

**Certbot fails with `... did not match this challenge (got "ok")`**: the
challenge request reached something other than this VPS's `/var/www/certbot`.
Check `dig +short <domain>` prints the VPS IP (no proxying CDN), and that no
other nginx site claims the same `server_name`:

```bash
sudo nginx -T | grep -n "server_name"
```

**Rolling back the database**: stop the services, restore a snapshot, start
them again.

```bash
cd /var/www/easy-apply
sudo systemctl stop gunicorn-easy-apply celery-easy-apply
ls -1t backups/
sudo -u <VPS_USER> cp backups/db-<timestamp>.sqlite3 db.sqlite3
sudo rm -f db.sqlite3-wal db.sqlite3-shm
sudo systemctl start gunicorn-easy-apply celery-easy-apply
```

**Checking the box by hand**:

```bash
sudo systemctl status gunicorn-easy-apply celery-easy-apply nginx redis-server
sudo journalctl -u gunicorn-easy-apply -n 50
sudo systemctl list-timers easy-apply-housekeeping.timer
sudo tail -n 50 /var/log/nginx/error.log
```
