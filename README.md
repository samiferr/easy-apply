# Easy Apply

Easy Apply is a Django web app for job seekers to keep a single, well-organized
record of everything that goes into a resume — soft skills, technical skills,
languages, work experience, degrees and certificates — and export it all as a
clean Markdown recap in one click.

## Features

- **AI job post analysis** — paste a job posting URL (or the description
  text) and DeepSeek breaks it into a **fixed set of 13 sections**
  (Overview, Company, Location & work arrangement, Compensation & benefits,
  How to Apply, Responsibilities, Required/Desirable Technical Skills,
  Desirable Soft Skills, Languages, Education & Certifications, Worth
  noting, Possible red flags). The list is closed — `jobs/sections.py` is the
  single source of truth and the importer discards anything the AI invents.
- **Per-requirement matching** — each of the 8 matched sections is compared
  against **only the part of your profile it maps to**, so a skills check
  never sees your salary expectations. Every row gets a
  strong/partial/none verdict plus a one-sentence justification naming the
  specific skill, role or credential behind it.
- **Add to my profile** — spot a requirement you meet but never recorded?
  One click opens a pre-filled review form; saving it adds the item to the
  right part of your profile and re-evaluates **that one row only**.
- **Everything runs in the background** — job analysis, resume analysis,
  matching and resume generation are all Celery tasks with live progress
  and step-by-step status. No request ever blocks on an AI call.
- **Bilingual (EN / FR)** — the whole interface, including the legal pages,
  plus the AI analysis itself, which answers in the language you are using.
- **Tailored resume + PDF export** — once a job is analyzed (and, ideally,
  matched), generate a resume written for *that* posting: DeepSeek rewrites
  your recorded experience in the job's own vocabulary, the document is
  assembled from `templates/resume_template.md`, and you get it as editable
  Markdown. Tweak anything, then export a clean, print-ready PDF (or the
  `.md`).
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

- **Backend:** Django 5, SQLite in WAL mode (**Postgres recommended in
  production** — the Celery worker writes to the same database as the web
  process)
- **Background jobs:** Celery + Redis — every AI call runs off the request cycle
- **Frontend:** Django templates + Tailwind CSS (compiled via the Tailwind CLI)
  + Alpine.js for lightweight interactivity (tabs, modals, dark mode)
- **Static files:** WhiteNoise (compressed, hashed, cache-friendly in production)

## Project layout

```
config/         Django project settings, root URLconf
accounts/       Custom user model, profile, auth & security views
jobs/           Job post analysis: the fixed section enum (sections.py), the
                add-to-profile registry (profile_targets.py), URL fetcher,
                prompts, importer, matcher and Celery tasks
resume/         Resume upload -> AI parsing -> review -> profile auto-fill,
                plus job-tailored resumes (Markdown draft -> edit -> PDF)
skills/         Soft/technical skill categories and per-user skills
languages/      Languages and per-user proficiency
experience/     Work experience (each role has ExperienceHighlight bullet rows)
education/      Degrees and certificates
preferences/    Job preferences (salary, location, arrangement) and the
                benefit list a job's Compensation section is matched against
legal/          Privacy, terms, cookies, legal notice and contact pages
core/           Landing page, dashboard, Markdown export, scoped profile
                slices (utils.py), shared AI client (ai.py) and the AITask
                progress model every AI path reports through
locale/fr/      French message catalogue
templates/      Shared base layout, partials, and per-app templates
                (resume_template.md is the tailored-resume skeleton)
static/src/     Tailwind input CSS (source of truth)
static/dist/    Compiled Tailwind output (generated, but committed so the
                app runs without a Node toolchain in production)
static/js/      Bundled Alpine.js, plus ai-progress.js and job-analysis.js
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

### 3. Redis and the Celery worker

Every AI call runs in a background task. In development, `CELERY_TASK_ALWAYS_EAGER`
defaults to the value of `DEBUG`, so tasks run inline and **you need neither
Redis nor a worker** to try the app or run the tests.

In production (or to exercise the real queue locally), set
`CELERY_TASK_ALWAYS_EAGER=False`, run Redis, and start a worker alongside the
web process:

```bash
celery -A config worker -l info --concurrency=2
```

Keep concurrency low on SQLite: the worker writes to the same database file as
the web process. SQLite is put in WAL mode automatically
(`core/apps.py`), and no AI call is ever made inside an open transaction — but
**Postgres is the recommended production database** for exactly this reason.

Two housekeeping commands are worth scheduling:

```bash
python manage.py sweep_stuck_ai_tasks   # on worker startup: fail tasks a crash left running
python manage.py prune_ai_tasks         # periodically: delete finished task records
```

### 4. Translations (EN / FR)

The French catalogue lives in `locale/fr/LC_MESSAGES/`. After changing any
user-facing string:

```bash
python manage.py makemessages -l fr    # requires gettext
# ...fill in the new msgstr entries...
python manage.py compilemessages -l fr
```

The language switcher in the top bar posts to Django's `set_language` view and
stores the choice in the `django_language` cookie, so no URL changes.

### 5. Log in and try it out

Register an account at `/accounts/register/`, then explore the dashboard,
add a few skills/languages/experience/education entries, and download your
recap from the dashboard or `/recap/preview/`.

## AI job post analysis

Under `/jobs/`, a user pastes a job posting URL (or, as a fallback, the
description text directly — useful for sites that block scrapers or require
JavaScript). Submitting **enqueues** the analysis and redirects straight to the
detail page, which shows live progress; the request never waits on an AI call.

### The pipeline

```
chord(
  chain(fetch_job_text → extract_job_sections),
  group(match_job_section × one per matched section),
) → finalize_job_analysis
```

1. **`services/fetcher.py`** fetches the URL server-side and extracts readable
   text. Since this fetches arbitrary user-supplied URLs from the server, it
   includes SSRF protections: only `http(s)`, every resolved IP — including on
   each redirect hop — checked against private/loopback/link-local/reserved
   ranges, and a size-capped response body.
2. **`services/deepseek_client.py`** holds three separate prompts, kept apart
   so each call carries the smallest possible payload: extraction, per-section
   matching, and single-element matching.
3. **`services/importer.py`** defensively parses the response. Wrong types,
   missing keys and invalid choices are coerced to safe defaults, and — the
   important part — **any section key outside the closed enum is discarded**,
   duplicates are merged, and a prose section never keeps rows (nor a row
   section prose).
4. **`services/matcher.py`** evaluates one section at a time.

Each `match_job_section` task records its own failure on the section and
returns normally, so **one failing section never poisons the chord** — the
other tabs finish and the user retries just that one.

### The fixed sections

`jobs/sections.py` is the single source of truth for the rail order, which
sections carry evaluable rows, which slice of the profile each is compared
against, and which profile object its "Add to my profile" button creates:

| Section | Rows | Matched against |
|---|---|---|
| Overview, Company, How to Apply, Worth noting, Possible red flags | prose | — |
| Location & work arrangement | yes | Job preferences |
| Compensation & benefits | yes | Job preferences (salary + benefits) |
| Responsibilities | yes | Experience + technical skills |
| Required / Desirable Technical Skills | yes | Technical skills |
| Desirable Soft Skills | yes | Soft skills |
| Languages | yes | Languages |
| Education & Certifications | yes | Degrees + certificates |

Adding a section later is one entry in `SECTIONS` — not a chain of `if`
branches across services, views and templates.

### Scoped matching

`core.utils.build_profile_slice(user, section_key)` returns **only** the mapped
part of the profile. A technical-skills check receives your technical skills
and nothing else — not your salary expectations, not your languages. This is
both a privacy property and a cost one: payloads are a fraction of the size of
the old single all-requirements-plus-whole-profile call.

If a slice is empty, **no API call is made at all**: every row in that section
is marked "not covered" with a message pointing at the profile tab that would
fill it.

`build_profile_snapshot` still exists for the tailored-resume path, which
legitimately needs everything.

### Add to my profile

Every matched row carries an **Add to my profile** button. It opens a
server-rendered modal containing a real Django form, pre-filled from the row's
text. On submit the object is created in the right part of your profile
(`jobs/profile_targets.py` maps each section to its form and target), and
**only that one row** is re-evaluated — the page never reloads and no other row
is touched. Duplicates come back as a form error in the modal rather than a 500.

To enable any of this, set `DEEPSEEK_API_KEY` in `.env` (get one at
platform.deepseek.com). Without it, the feature shows a clear "AI analysis
isn't configured" error instead of failing silently.

## Background processing and progress

All four AI paths — resume analysis, job analysis, matching and tailored-resume
generation — run as Celery tasks. **No view calls DeepSeek directly.**

`core.models.AITask` is the single progress record they all report through, so
the UI has one widget (`templates/partials/_ai_progress.html`) and one polling
contract instead of four. It tracks `steps_done` / `steps_total` /
`current_step`, so a job analysis reports *"5 of 11 — Matching Languages"*
while single-call tasks render an indeterminate bar.

`GET /tasks/<id>/status/` returns that state as JSON, owner-scoped (404 for
anyone else). The front end (`static/js/ai-progress.js`) polls every 2s,
backs off to 5s after 30 seconds, **stops on a terminal state**, and pauses
while the browser tab is hidden. The analysis page additionally polls
`/jobs/<pk>/analysis-state/`, which returns every section's state in one call
rather than 13.

Retries are deliberate: transient failures (timeouts, 429s, 5xx) retry with
exponential backoff, while a missing API key or malformed JSON — both
deterministic — fail immediately rather than burning quota.

## Tailored resume & PDF export

On an analyzed job's detail page, **Generate tailored resume**
(`resume/services/tailored.py`) writes a resume for that specific posting:

1. The job — its framing plus every extracted requirement, tagged with the
   `strong`/`partial`/`none` verdict and evidence from "Match to my profile"
   when it has been run — goes to DeepSeek together with a full snapshot of
   the user's profile (`core.utils.build_resume_snapshot`, which adds contact
   details, locations and dates to the snapshot the matcher uses) and the raw
   `templates/resume_template.md` skeleton.
2. The model returns only the *content* of each section (summary, grouped
   skills, per-role highlights rewritten in the job's vocabulary, education,
   languages) as JSON, under a prompt that forbids inventing employers,
   dates, credentials or skills the user hasn't recorded.
3. `render_markdown()` assembles that content into one Markdown document,
   following the `##` headings found in `templates/resume_template.md` — edit
   that file and every future resume follows the new shape. The header (name,
   location, phone, email, links) is built straight from the profile, never
   from the model, and sections the model returned nothing for are dropped
   instead of printed empty.

The draft is stored on a `TailoredResume` row (one per job) and opened in a
Markdown editor. Nothing is auto-sent anywhere: the user edits the text,
saves, and exports when happy.

**PDF export** (`resume/services/pdf.py`) renders that Markdown with
ReportLab — no headless browser or system libraries needed. It covers the
subset a resume uses (headings, bullets, bold/italic/code, links, rules);
everything above the first `##` heading becomes the centered header block,
and unrecognized syntax falls through as plain text rather than raising.
Set `RESUME_PDF_PAGE_SIZE=a4` in `.env` for A4 instead of US Letter.

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
- **Run Redis and at least one Celery worker** — with `DEBUG=False`,
  `CELERY_TASK_ALWAYS_EAGER` defaults to False, so without a worker every AI
  request queues forever. Start one with
  `celery -A config worker -l info --concurrency=2`.
- **Swap SQLite for Postgres.** This matters more than it used to: the worker
  and the web process now write to the same database. SQLite is put in WAL
  mode with a busy timeout and no AI call is made inside an open transaction,
  which makes single-instance SQLite workable — but Postgres is the right
  answer for anything real.
- Fill in every `LEGAL_*` variable. The legal pages ship with visible `TODO:`
  placeholders for the entity name, address, jurisdiction, hosting provider and
  privacy contact.
- Run `python manage.py compilemessages -l fr` in your build so the French
  catalogue is available (`.mo` files are not committed).
- Schedule `python manage.py prune_ai_tasks`, and run
  `python manage.py sweep_stuck_ai_tasks` on worker startup so a crashed worker
  never leaves a permanent spinner in the UI.
