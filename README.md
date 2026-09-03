# Easy Apply

Easy Apply is a Django web app for job seekers to keep a single, well-organized
record of everything that goes into a resume — soft skills, technical skills,
languages, work experience, degrees and certificates — and export it all as a
clean Markdown recap in one click.

## Features

- **Soft skills & technical skills**, grouped by category, with a proficiency
  level (Beginner → Expert).
- **Languages** with a proficiency scale (Basic → Native).
- **Work experience** with a visual timeline.
- **Education**: degrees and certificates (with credential links and
  expiration tracking).
- **One-click Markdown recap** — preview it in the browser, copy it to the
  clipboard, or download it as a `.md` file, generated live from your data.
- **Full account system**: registration, login/logout, email-based password
  reset & recovery, profile editing (with avatar upload), a security page
  (change password, delete account), all built on Django's auth framework
  with a custom email-based user model.
- **Responsive, accessible UI** built with Tailwind CSS and Alpine.js
  (light/dark mode, mobile navigation, accessible forms, toast messages).

## Tech stack

- **Backend:** Django 5, SQLite (swap `DATABASES` for Postgres in production)
- **Frontend:** Django templates + Tailwind CSS (compiled via the Tailwind CLI)
  + Alpine.js for lightweight interactivity (tabs, modals, dark mode)
- **Static files:** WhiteNoise (compressed, hashed, cache-friendly in production)

## Project layout

```
config/         Django project settings, root URLconf
accounts/       Custom user model, profile, auth & security views
skills/         Soft/technical skill categories and per-user skills
languages/      Languages and per-user proficiency
experience/     Work experience
education/      Degrees and certificates
core/           Landing page, dashboard, Markdown export utility
templates/      Shared base layout, partials, and per-app templates
static/src/     Tailwind input CSS (source of truth)
static/dist/    Compiled Tailwind output (generated, but committed so the
                app runs without a Node toolchain in production)
static/js/      Bundled Alpine.js (no external CDN dependency)
```

## Getting started

### 1. Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then edit as needed

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

The app seeds a handful of common soft-skill and technical-skill categories
(Communication, Leadership, Programming Languages, Databases, ...) via a data
migration, so new users have somewhere to start. Add more from `/admin/`.

### 2. Frontend (Tailwind CSS)

The compiled CSS in `static/dist/output.css` is committed, so you don't need
Node.js just to run the app. If you're changing styles, install the toolchain
and rebuild:

```bash
npm install
npm run build:css     # one-off build
npm run dev:css        # watch mode while developing
```

`static/js/alpine.min.js` is a bundled copy of Alpine.js (`npm run build:js`
regenerates it from `node_modules`) — the app doesn't load any JS from a CDN.

### 3. Log in and try it out

Register an account at `/accounts/register/`, then explore the dashboard,
add a few skills/languages/experience/education entries, and download your
recap from the dashboard or `/recap/preview/`.

## Password reset & recovery

`/accounts/password-reset/` sends a signed, expiring link (3 days) to the
account's email address to set a new password — this covers both "I forgot
my password" and "I need to recover access to my account". In development,
`EMAIL_BACKEND` defaults to the console backend, so reset links are printed
to the terminal instead of actually being emailed. Configure `EMAIL_*` in
`.env` to send real emails in production.

## Deployment notes

- Set `DEBUG=False`, a strong `SECRET_KEY`, and real `ALLOWED_HOSTS` /
  `CSRF_TRUSTED_ORIGINS` in your environment.
- Run `python manage.py collectstatic` — WhiteNoise serves the compressed,
  hashed static files directly from the Django app (no separate static host
  required).
- Run behind a real WSGI server, e.g. `gunicorn config.wsgi:application`.
- Swap the SQLite `DATABASES` entry for Postgres (or your database of choice)
  for anything beyond local development.
