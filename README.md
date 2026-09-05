# Easy Apply

Easy Apply is a Django web app for job seekers to keep a single, well-organized
record of everything that goes into a resume — soft skills, technical skills,
languages, work experience, degrees and certificates — and export it all as a
clean Markdown recap in one click.

## Features

- **AI job post analysis** — paste a job posting URL (or the description
  text) and DeepSeek structures it into a `JobPost` (title, summary,
  location/work arrangement, compensation & benefits, company info,
  application instructions, red flags, growth language, ...) with its
  requirements grouped into categories (Responsibilities, Required
  Qualifications, Preferred Qualifications, ...), each holding individual,
  atomic requirement rows.
- **Match to my profile** — for an analyzed job, DeepSeek evaluates every
  extracted requirement individually against your profile and shows, right
  beside each one, whether it's a strong/partial/no match and *which*
  specific skill, role or credential of yours supports that verdict — plus
  an overall fit-score meter for the job.
- **Import from resume** — upload a PDF/DOCX/TXT resume and DeepSeek extracts
  your profile info, skills, languages, work experience and education. You
  review every item on a checklist (duplicates of what you already have are
  flagged and unchecked by default) before anything is added — nothing is
  overwritten silently.
- **Soft skills & technical skills**, grouped by category, with a proficiency
  level (Beginner → Expert).
- **Languages** with a proficiency scale (Basic → Native).
- **Work experience** with a visual timeline — each role's highlights are
  recorded as individual bullet-point rows (add/remove them dynamically on
  the form) rather than one free-text block.
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
jobs/           Job post analysis: models, URL fetcher, DeepSeek client, importer
resume/         Resume upload -> AI parsing -> review -> profile auto-fill
skills/         Soft/technical skill categories and per-user skills
languages/      Languages and per-user proficiency
experience/     Work experience (each role has ExperienceHighlight bullet rows)
education/      Degrees and certificates
core/           Landing page, dashboard, Markdown export utility, shared AI client (core/ai.py)
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

## AI job post analysis

Under `/jobs/`, a user can paste a job posting URL (or, as a fallback, paste
the description text directly — useful for sites that block scrapers or
require JavaScript). The pipeline (`jobs/services/`):

1. **`fetcher.py`** fetches the URL server-side and extracts its readable
   text. Since this fetches arbitrary user-supplied URLs from the server, it
   includes basic SSRF protections: only `http(s)` is allowed, every resolved
   IP — including on each redirect hop — is checked against
   private/loopback/link-local/reserved ranges, and the response body is
   size-capped.
2. **`deepseek_client.py`** sends the extracted (or pasted) text to the
   [DeepSeek](https://platform.deepseek.com/) chat completions API in JSON
   mode, with a prompt that mirrors a structured "should I apply?" reading
   guide (title/summary, responsibilities, required vs. preferred
   qualifications, location & work arrangement, compensation & benefits,
   company info, application instructions, plus red flags / growth language /
   diversity signals).
3. **`importer.py`** defensively parses that JSON (wrong types, missing keys,
   and invalid choices are all coerced to safe defaults rather than crashing)
   into the relational schema:
   - `JobPost` — the parent record: one row per analyzed posting, holding
     every "global" attribute above.
   - `RequirementCategory` — a named group of requirements on a job
     (Responsibilities, Required Qualifications, ...).
   - `Requirement` — one row per individual, atomic requirement line, under
     its category.

   Analysis runs synchronously inside the request (no task queue is set up),
   so submitting the form takes a few seconds; the job's `status` field
   (`pending` → `processing` → `completed`/`failed`) and a friendly
   `error_message` make failures (bad URL, blocked scraper, missing API key,
   AI/timeout errors) visible in the UI with a "Try again" action instead of
   a crash.

To enable it, set `DEEPSEEK_API_KEY` in `.env` (get one at
platform.deepseek.com). Without it, the feature shows a clear
"AI analysis isn't configured" error instead of failing silently.

### Match to my profile

On an analyzed job's detail page, "Match to my profile" (`jobs/services/matcher.py`)
sends the job's full requirement list — every row, tagged with its real
database id — together with a structured snapshot of the user's profile
(`core.utils.build_profile_snapshot`) to DeepSeek in a single request whose
prompt explicitly instructs it to evaluate each requirement independently,
one by one, rather than forming one overall impression. It returns a
verdict (`strong` / `partial` / `none`) plus a one-sentence, specific
justification for every requirement id, which are written back onto each
`Requirement` row (`match_status`, `match_evidence`) and rendered right next
to that requirement, alongside an overall fit-score meter
(`JobPost.requirement_match_summary`, weighting strong matches fully and
partial matches at half). Unrecognized ids, invalid statuses, and
non-integer ids in the AI's response are dropped rather than applied. If the
user's profile has nothing recorded yet, the action is skipped with a
message pointing them at their profile instead of spending an API call on a
guaranteed all-"none" result.

## Import from resume

Under `/resume/upload/` (also linked from the Profile page and dashboard), a
user uploads a resume and DeepSeek turns it into the same shape used
throughout the rest of the app. The pipeline (`resume/services/`):

1. **`extractor.py`** pulls plain text out of the uploaded PDF (`pypdf`),
   DOCX (`python-docx`), or TXT file — with friendly errors for encrypted
   PDFs, scanned/image-only PDFs, or corrupted files.
2. **`deepseek_resume.py`** sends that text to DeepSeek (via the same shared
   `core/ai.py` client the job-analysis feature uses) asking for profile
   info, soft/technical skills, languages, work experience (with highlight
   bullets), degrees and certificates — steered to reuse the site's existing
   skill categories where they fit.
3. **`importer.py`** does the rest in two steps:
   - `build_review_sections()` compares every suggested item against what
     the user already has (same skill name + kind, same language, same
     company + title, same school + degree, same certificate name + issuer)
     and flags matches as "Already have this". Profile fields are only
     offered when the corresponding field is currently empty — the app never
     proposes overwriting something you already filled in.
   - The review page (one form, a checkbox per item, pre-checked except for
     flagged duplicates) posts back just the list of checked keys;
     `apply_selected()` re-reads the AI response stored on the
     `ResumeImport` row server-side and creates rows only for what was
     checked, inside one transaction.

Nothing touches your profile until you explicitly submit the review page, so
a bad AI guess costs you an unchecked box, not corrupted data.

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
