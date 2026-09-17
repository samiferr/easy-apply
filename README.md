# Easy Apply

Easy Apply is a Django web app for job seekers to keep a well-organized record
of everything that goes into a resume — soft skills, technical skills,
languages, work experience, degrees and certificates — and export it all as a
clean Markdown recap in one click.

One account can hold **several profiles**. A profile is a self-contained
workspace with its own content, its own analyzed job posts, its own resumes —
and its own language, chosen when the profile is created and used by every AI
call made inside it.

## Features

- **Multiple profiles, one account** — a profile is a workspace, not just a
  page of personal details: skills, languages, experience, education, job
  preferences, analyzed job posts, resume imports and tailored resumes all
  belong to exactly one profile. Keep a "Backend engineer" profile and a
  "Data analyst" profile side by side and switch between them from the top
  bar; neither ever sees the other's content.
- **A profile's language is chosen, then enforced** — you pick it when you
  create the profile (there is no default to fall through to) and it is fixed
  from then on. Every AI call made in that profile — job extraction,
  requirement matching, resume parsing, resume writing — is instructed to
  answer in it, and everything the app assembles itself (recap headings,
  resume section titles, dates, "Present") is rendered in it too. Switching
  profiles switches the interface language with them. Working in another
  language means creating another profile, which is what keeps a profile's
  content from ever ending up half-translated.
- **AI job post analysis** — paste the job description text and DeepSeek
  breaks it into a **fixed set of 13 sections**
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
  plus the AI analysis itself, which answers in the active profile's language.
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
  The shell is borderless and has no top bar — the sidebar is the app's only
  chrome and shares one canvas with the content — capped at 96rem and centred, and every foreground/background pair in it is
  measured against WCAG 2.2 rather than eyeballed. See **Design system** below.
- **An operator console at `/staff/`** for running this as a service: plans,
  subscriptions and monthly usage quotas; feature flags with percentage
  rollouts; in-product announcements; runtime kill switches (maintenance mode,
  AI, sign-ups); audited "sign in as customer" support sessions; system health
  and AI-queue screens; GDPR data export and erasure; and an append-only audit
  log of every staff action. Access is a role, not just `is_staff`. See
  **The operator console** below.

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
accounts/       Custom user model, the Profile (workspace) model, profile
                CRUD/switching, auth & security views
jobs/           Job post analysis: the fixed section enum (sections.py), the
                add-to-profile registry (profile_targets.py), prompts,
                importer, matcher and Celery tasks
resume/         Resume upload -> AI parsing -> review -> profile auto-fill,
                plus job-tailored resumes (Markdown draft -> edit -> PDF)
skills/         Soft/technical skill categories and per-profile skills
languages/      Languages and per-profile proficiency
experience/     Work experience (each role has ExperienceHighlight bullet rows)
education/      Degrees and certificates
preferences/    Job preferences (salary, location, arrangement) and the
                benefit list a job's Compensation section is matched against
legal/          Privacy, terms, cookies, legal notice and contact pages
staffportal/    The operator console at /staff/: plans, subscriptions and
                usage quotas, feature flags, announcements, runtime settings,
                impersonation, health checks, the AI queue and the audit log
core/           Landing page, dashboard, Markdown export, scoped profile
                slices (utils.py), shared AI client (ai.py), the active-profile
                middleware (middleware.py), the AI language contract
                (language.py) and the AITask progress model every AI path
                reports through
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

The language switcher in the sidebar's user menu posts to Django's
`set_language` view and
stores the choice in the `django_language` cookie, so no URL changes. That
switcher only changes the *interface*: what the AI answers in comes from the
active profile (see **Profiles** below).

### 5. Log in and try it out

Register an account at `/accounts/register/` — the form asks which language
your first profile works in — then explore the dashboard, add a few
skills/languages/experience/education entries, and download your recap from
the dashboard or `/recap/preview/`. Add a second profile from the switcher at
the foot of the sidebar to see the workspaces stay separate.

## Profiles (workspaces)

A `Profile` is not a page of personal details; it is the thing everything else
hangs off. `UserSkill`, `UserLanguage`, `WorkExperience`, `Degree`,
`Certificate`, `JobPreference`, `JobPost`, `ResumeImport` and `TailoredResume`
each carry a `profile` foreign key and no `user` foreign key at all — so there
is no query that can accidentally reach across profiles, and deleting a profile
takes its content with it. `accounts.tests.ProfileIsolationTests` guards that
shape.

### The active profile

`core.middleware.ActiveProfileMiddleware` resolves `request.profile` once per
request (lazily, like `request.user`) from the `active_profile_id` session key,
falling back to the user's oldest profile if the session points at one that no
longer exists. Views filter and write through it; nothing reads
`request.user.skills` any more, because that relation is gone.

Every account has at least one profile: a `post_save` signal creates one for a
new user, the `accounts.0002_profile_workspaces` migration backfills one for
any pre-existing account that lacked one, and the delete view refuses to remove
the last one.

### The language contract

A profile's language is required at creation (the select has a blank first
option, so it cannot be defaulted into silently) and is **not editable
afterwards** — the rename form drops the field. That is what lets the app
promise that a profile's content is all in one language: the alternative,
letting the language change under content already written, would leave a
profile permanently mixed.

`core/language.py` is the single place that turns a language code into
instructions for the model:

- `language_clause(code)` is prepended to the user message of **every** AI call
  — job extraction, section matching, single-element re-matching, resume
  parsing and tailored-resume writing.
- `use_language(code)` is a `translation.override` wrapper used around anything
  the app assembles itself, so the parts we write match the parts the model
  writes: the Markdown recap, the tailored resume's section headings, the
  profile slices sent into a matching prompt (they carry display strings like
  *Expert* and *Jan 2020 – Aujourd'hui*), and the "nothing in your profile
  covers this" evidence line written when a slice is empty.

Because the source is the profile and not `get_language()`, re-running an
analysis months later in a different browser language produces the same
language it did the first time. Switching profiles also switches the interface
language to match, so a French workspace is never read through an English UI.

## Design system

Tokens live in `static/src/input.css` as CSS variables and are exposed to
Tailwind through `tailwind.config.js`, so a component is declared once and both
themes follow it — no `bg-white dark:bg-slate-900` pair on every element.

| Token | Light | Dark | Used for |
| --- | --- | --- | --- |
| `canvas` | slate-100 | slate-950 | the app background — the sidebar and the content both sit on it |
| `surface` | white | slate-900 | cards, menus, inputs |
| `surface-sunken` | slate-100 | slate-800 | wells, progress tracks, code |
| `line` | slate-200 | slate-800 | decorative rules and dividers |
| `line-strong` | `#7f8fa5` | `#59687c` | the boundary that *identifies* a form control |

### The shell has no top bar and no dividing rules

The sidebar and the content are one continuous surface. Structure comes from
spacing, from the cards the content sits in, and from the active nav row's
tinted pill.

There is **no top bar**: the sidebar is the app's only chrome. Navigation runs
down the top of the column, and the account block pinned to its foot carries
what a bar would have — the workspace switcher
(`partials/profile_switcher.html`) and the user menu
(`partials/user_menu.html`: personal info, profiles, theme, the FR/EN language
switcher, the recap export, admin and log out). Both panels open *upwards*, so
they stay on screen and keep working when the sidebar is collapsed to icons.
Nothing spans the width of the screen, so a page begins with its own
breadcrumb.

Layout is a flex row inside a centred `max-w-shell` container, so the sidebar
is `sticky` rather than `fixed` and the content column needs no matching
padding. Under `md` the sidebar leaves the flow, becomes a `surface` drawer
over a scrim, and rejoins the canvas at `md` and up. The drawer's opener is a
single floating button in the corner — the only chrome that overlays content —
and `main` carries matching top padding below `md` so nothing starts beneath
it.

### Every page wears the same header

Breadcrumb, title, subtitle — in that order, in the same place, on every
screen. It is rendered **once**, in `templates/base_app.html`, and a page only
fills blocks:

```django
{% block breadcrumb %}
  {% url 'jobs:list' as jobs_list_url %}
  {% include "partials/_crumb.html" with crumb_label=_("Job posts") crumb_url=jobs_list_url only %}
  {% include "partials/_crumb.html" with crumb_label=_("Analyze a job post") only %}
{% endblock %}
{% block page_title %}{% trans "Analyze a job post" %}{% endblock %}
{% block page_subtitle %}{% trans "Paste the job description…" %}{% endblock %}
{% block page_actions %}<a href="…" class="btn-primary">…</a>{% endblock %}
```

| Block | What goes in it |
| --- | --- |
| `breadcrumb` | the crumbs after "Dashboard", one `partials/_crumb.html` each |
| `breadcrumb_root` | override only to make the root crumb the current page (the dashboard does) |
| `page_title` | the `<h1>`, the one on the page |
| `page_subtitle` | one line saying what the screen is for |
| `page_actions` | the screen's primary buttons, right-aligned on the title row |
| `page_title_badge` / `page_meta` | optional extras beside and under the title (a status badge, a link out) |
| `content` | everything below the header |

`partials/_crumb.html` takes `crumb_label` and, for an ancestor, `crumb_url`;
the last crumb has no URL and renders as `aria-current="page"` text. Pass
`only` so a previous crumb's URL can't leak into the next one, and resolve
URLs with `{% url … as … %}` first — `{% include %}` arguments take variables,
not tags.

Two rules keep the header from moving:

- **Nothing renders above it.** With no top bar, the breadcrumb is the first
  thing on the page; flash messages sit *below* the header, and anything above
  the breadcrumb would shift it every time one appeared.
- **One container, one width.** Every screen lives in `.page-shell`
  (`max-w-7xl`), so the title starts on the same pixel whether the page is a
  wide list or a narrow form. A form caps itself with `max-w-2xl` and **no**
  `mx-auto`, so it stays left-aligned under its own title instead of drifting
  to the middle of the column.

This replaced a set of per-page `← Back to …` links that each sat in their own
spot, and per-page containers that ranged from `max-w-lg` to `max-w-7xl` — so
the title jumped horizontally as you moved between a list, its add form and
its delete confirmation. Add, edit and delete screens are pages like any
other, and now say so.

`partials/profile_base.html` and `accounts/settings_base.html` are thin shells
on top of this: they add a content column and a tab nav respectively, and fill
the shared crumb their screens have in common. Legal pages are public, so they
can't extend `base_app.html`; `legal/_legal_base.html` builds the same header
from the same `.page-shell` / `.page-header` / `.breadcrumb` classes, taking
its title from `LegalPageView.page_title` so the `<h1>` and the breadcrumb
cannot disagree. The marketing landing page and the auth cards (log in,
register, password reset) have no breadcrumb trail to show and keep their own
centred layouts.

### Contrast is measured, not estimated

Every pair the app actually renders was computed against WCAG 2.2: 4.5:1 for
body text (1.4.3) and 3:1 for the boundaries that identify controls (1.4.11).
That moved several defaults:

- `text-slate-400`, the old muted colour, is **2.56:1 on white** — it was never
  readable in light mode. Muted text is now slate-600 (7.58:1 on a card,
  6.92:1 on the canvas), one value that is safe on every app surface.
- Input borders were slate-300, **1.48:1**. `line-strong` is the lightest grey
  that still clears 3:1 on both surfaces (3.30:1 on white, 3.14:1 on slate-900).
- Body copy is slate-700 rather than slate-900: 10.4:1 is far past the floor
  without the halation of maximum contrast.

After a palette edit, re-check by rendering each screen and asserting that no
sub-4.5:1 foreground is emitted — the values above are all reproducible from
the sRGB relative-luminance formula in WCAG 2.2.

### Other readability choices

- Long-form copy (`.measure`, `.page-lead`, `.legal-prose`) is capped at 65
  characters a line.
- `text-wrap: balance` on headings, `text-wrap: pretty` on paragraphs.
- Hover-only row controls stay reachable: they reveal on focus as well as
  hover, and are always visible below `md`, where there is no hover.
- Collapsing the sidebar keeps every link's accessible name — the labels become
  `sr-only` rather than `display: none`, which would have left ten unnamed
  icon links.

### One heading class per context, everywhere

Every screen's `<h1>` uses one of two shared classes rather than a hand-typed
`text-2xl font-bold ...` that quietly drifts from page to page:

- **`.page-title`** — the heading rendered by the page header above, so it is
  every screen that has one: dashboard, lists, detail views, add/edit forms,
  delete confirmations, legal pages, account settings. `heading-2xl`, stepping
  up to `heading-3xl` at `sm:`. No page writes this tag itself.
- **`.card-title`** — the heading inside a narrow single-purpose card that has
  no page header of its own: log in, register, password reset. One size down
  (`heading-xl`, no responsive step) because the card's own width sets the
  scale, not the viewport — a responsive bump here would make a short heading
  look oversized in a `max-w-md` column.

Both are declared once in `static/src/input.css`; no page defines its own
heading size. Because the header owns the `<h1>`, a screen also cannot end up
with two of them — `resume_review.html` previously carried a second `<h1>` in
each of its short-message states, which is the kind of drift the shared header
exists to catch.

#### Headings sit 30% above the body scale

Every heading size comes from the `heading-*` scale in `tailwind.config.js`,
which is Tailwind's own scale multiplied by 1.3 — size and leading together,
so a heading's type block keeps its proportions and a title that wraps to two
lines does not crowd itself. `heading-2xl` is `text-2xl` × 1.3, and so on down
the scale.

The ratio is stated once, there, rather than as `text-[1.95rem]` at each call
site, so changing it again is one edit. **Never hard-code a heading size** in
`input.css` or a template: reach for a `heading-*` step, and every heading in
the app moves together. `<h1>`–`<h3>` are all on it — the shared classes
above, the `legal-prose h2` rule, and the handful of headings that still carry
their size inline (the landing page, the security tab, section headings inside
cards).

## Skills: one tab per category

The soft- and technical-skills screens split their skills into a tab per
category, over a single panel, rather than the grid of half-width category
cards they used to show. The tabs are the categories the profile actually has
skills in — the same set the grid showed — so a profile with nothing recorded
yet still gets the plain empty state rather than a strip of empty tabs.

`templates/skills/_skill_category_tabs.html` owns it, with the `.tab-strip`
component in `static/src/input.css`. Three things are worth knowing:

- **State lives in the URL fragment** (`#category-<pk>`), written with
  `history.replaceState` so it neither stacks history entries nor makes the
  browser jump to an element. `skills.views.skills_url` builds the same
  fragment, so adding, editing or deleting a skill returns you to the category
  you were working in instead of dropping you on the first tab.
- **The fragment deliberately matches no element id.** Panels are
  `panel-category-<pk>`, tabs are `tab-category-<pk>`; if the fragment matched
  either, restoring it on load would scroll the page.
- **A hash change is not always a page load.** Following a link to another tab
  on the page you are already on is a same-document navigation: nothing
  reloads, so the component listens for `hashchange` as well as reading the
  fragment on init. Without that the fragment would change and the tabs would
  not — the one bug this feature actually shipped with in review.

Keyboard behaviour follows the WAI-ARIA tabs pattern: the strip is a single
tab stop, arrow keys move between tabs and take focus with them, Home and End
jump to the ends.

## Confirming a delete

Every destructive action — removing a skill, a job post, a whole profile —
shows the same confirmation page instead of a browser-native `confirm()`
popup, which is unstyled, not screen-reader-visible until it's already open,
and easy to click through on muscle memory.

`templates/core/confirm_delete.html` is the one template every delete view
renders, via a small context contract (`heading`, `detail`, `warning`,
`cancel_url`, `parent_crumbs`, `confirm_label`). It is a page like any other:
the question is its `page_title`, the consequence is its subtitle, and
`parent_crumbs` — a list of `{"label", "url"}` mappings — is the breadcrumb
trail back to wherever Cancel goes.

`core.mixins.ConfirmDeleteMixin` supplies all of it for the `DeleteView`-based
ones (mix it in before `DeleteView`; override
`get_heading`/`get_detail`/`cancel_url_name`, and set `parent_label` for the
crumb — or override `get_parent_crumbs` when the trail is deeper than one
screen). The handful of plain `View` subclasses (profile, tailored resume,
benefit) render it directly from their own `get()`. Either way, GET shows the
page and changes nothing; only POST deletes.

A couple of these carry a sharper warning than "This can't be undone" because
the delete cascades: removing a job post also removes the tailored resume
written for it, and removing a profile takes every skill, experience, job
preference and analyzed post recorded under it. Both are computed in
`get_warning()` from the actual related rows, not hard-coded.

One pitfall worth flagging for future views like this: a translatable string
assigned as a **class attribute** (`warning = _("...")`) is evaluated once, at
import time, in whichever language happens to be active then — not per
request. Either return it from a method, wrap it in `gettext_lazy` (what the
`parent_label` attributes do), or leave it to the template's own
`{{ warning|default:_("...") }}` fallback, which *does* re-evaluate per
request.

## AI job post analysis

Under `/jobs/`, a user pastes the job description text — that text is the only
input; the app never fetches a URL, so nothing depends on a careers site
allowing scrapers or rendering without JavaScript. Submitting **enqueues** the
analysis and redirects straight to the detail page, which shows live progress;
the request never waits on an AI call.

### The pipeline

```
chord(
  chain(read_job_text → extract_job_sections),
  group(match_job_section × one per matched section),
) → finalize_job_analysis
```

1. **`read_job_text`** takes the pasted description off the `JobPost` and
   hands it to the pipeline. There is no network call in this step — and, with
   no server-side URL fetching anywhere in the app, no SSRF surface to defend.
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

`core.utils.build_profile_slice(profile, section_key)` returns **only** the
mapped part of that profile. A technical-skills check receives your technical skills
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

Steps 1–3 all run under the profile's language: the prompt carries the
language clause, the snapshot's display strings are built inside
`use_language`, and the section headings come from a translated map keyed by
the template's own section keys — so a French profile gets *RÉSUMÉ
PROFESSIONNEL* over French prose, not French prose under English headings.

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
   skill categories where they fit, and to write everything it produces in the
   profile's language. The uploaded resume itself can be in any language: what
   lands in the profile is normalized into the one that profile works in.
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
a bad AI guess costs you an unchecked box, not corrupted data. Everything that
is created lands in the profile the upload belongs to — importing a resume into
one workspace never touches another.

## Password reset & recovery

`/accounts/password-reset/` sends a signed, expiring link (3 days) to the
account's email address to set a new password — this covers both "I forgot
my password" and "I need to recover access to my account". In development,
`EMAIL_BACKEND` defaults to the console backend, so reset links are printed
to the terminal instead of actually being emailed. Configure `EMAIL_*` in
`.env` to send real emails in production.

## The operator console (`/staff/`)

Everything a SaaS needs an operator to be able to do, in one place, gated on
`is_staff`. `django.contrib.admin` stays mounted at `/admin/` as the raw table
editor of last resort; `/staff/` is the product built for the people running
this one.

The console is **English only**, deliberately: it is an internal tool with one
operator language, and translating it would double the review surface of every
screen for nobody's benefit. Everything a *customer* ever sees — including the
maintenance page the console can switch on — is still fully translated.

### Access is a role, not a flag

`is_staff` is the door. What is behind it is a role on `staffportal.StaffMember`:

| Role | Adds |
| --- | --- |
| **Viewer** | Read the overview, accounts, billing, the queue and the audit log |
| **Support** | Suspend/reactivate, send password resets, write internal notes, impersonate, export an account's data |
| **Billing** | Change plans, subscriptions and usage counters |
| **Admin** | Feature flags, announcements, runtime settings, account deletion |
| **Superuser** | Everything, plus granting and revoking portal access |

A staff account with no `StaffMember` row reads as a **viewer** — turning on
`is_staff` by mistake exposes read-only screens, never the delete button.
Granting roles is superuser-only on purpose: any role that can hand out roles
can promote itself, which makes every other boundary decorative.

Two rules are enforced in one place (`staffportal/views/base.py`) so no screen
can forget them:

- a non-staff visitor gets **404, not 403** — a 403 confirms the portal is
  there;
- an **impersonated session can never reach the portal**, or "sign in as a
  customer" becomes a way to take a staff action the audit trail attributes to
  the customer.

### What it does

**Overview** — MRR, ARR, ARPA and 30-day churn; sign-ups and actives (DAU /
WAU / MAU and the DAU÷MAU stickiness ratio); an activation funnel from
"signed up" to "analyzed a job post" to "generated a resume"; AI success rate
by task kind; and a *needs attention* strip that puts failing health checks and
failed jobs above the vanity totals.

**Accounts** — searchable and filterable by status, plan and activity, with an
account screen that carries the customer's profiles, job posts, AI jobs, plan,
this period's usage against their allowances, the feature flags that are on for
them, internal support notes, and every staff action ever taken on them.
Actions: suspend (which also **ends their live sessions**, not just their next
login), reactivate, send the normal password-reset email (staff never see or
set a customer's password), change plan, reset this period's usage, export
their data, and delete the account.

**Impersonation** — "sign in as this customer", with a mandatory recorded
reason, a session that **expires by itself** (`impersonation_minutes`), a red
non-dismissible banner on every page while it is open, and an audit entry at
both ends. Staff cannot impersonate other staff unless they are a superuser.

**Plans, subscriptions and quotas** — plans carry a price and monthly
allowances where `NULL` means unlimited and `0` means *not included*. Every
account gets a subscription on the default plan at registration, so no code
path has to handle "user without a plan". Usage is counted in `UsageRecord`
rather than derived from `core.AITask`, because task rows are pruned on a
retention schedule and a billing period has to still add up after they are
gone. `external_customer_id` / `external_subscription_id` are where a real
payment provider's ids go when one is wired in — nothing here bills anyone.

**Feature flags** — off / on / staff-only / percentage rollout, plus per-account
overrides and per-plan entitlements. Bucketing is a hash of the flag key and the
account id, so a 10% rollout is the *same* 10% on every request and in every
process, and raising the percentage only ever adds accounts. A key with no row
evaluates to **off**, so deleting a flag retires its feature rather than
releasing it to everyone. Check one with `{% feature "key" as on %}` in a
template or `flags.is_enabled("key", user)` in Python.

**Announcements** — maintenance windows, incidents and release notes, shown as a
banner in the product to a chosen audience for a chosen window, dismissed per
browser in `localStorage`.

**Operations** — a health screen that answers both *is it up* (database,
migrations, Celery workers, the queue) and *is it configured like production*
(`DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`, HTTPS cookies, email backend, AI key,
`collectstatic`, the `LEGAL_*` placeholders, a default plan); the AI queue with
per-job retry and cancel; and the runtime settings below.

**Audit log** — append-only: `AuditLog.save()` refuses updates and
`delete()` refuses single-row deletes, so the only way to remove anything is the
retention command. Actor email and target label are denormalized so an entry
stays readable after the accounts it names are deleted — which is exactly the
entry someone will come asking about. Downloading the log is itself audited.

**Exports** — streaming CSVs for accounts, subscriptions, the queue and the
audit log, and a per-account JSON export covering every table, for GDPR Art. 20
(portability) and Art. 17 (erasure, via the delete flow).

### Runtime settings

Changed from `/staff/operations/settings/` with no deploy, and cached for 30
seconds so the per-request ones cost nothing:

| Key | Default | What it does |
| --- | --- | --- |
| `signups_enabled` | `True` | Closes registration without touching existing accounts |
| `maintenance_mode` | `False` | Everyone but staff gets a translated 503 page; staff keep full access so the fix can be verified before it is lifted |
| `ai_features_enabled` | `True` | Kill switch for every call to the AI provider |
| `enforce_quotas` | `False` | Whether plan allowances actually refuse work |
| `impersonation_minutes` | `30` | How long a "sign in as" session stays open |
| `audit_retention_days` | `365` | Used by `manage.py prune_audit_log` |
| `support_email` | `""` | Shown to customers on error and quota screens |

**Quota enforcement ships dark.** With `enforce_quotas` off — the default — the
product behaves exactly as it did before this app existed: usage is recorded,
nothing is refused. Turn it on once the allowances read correctly on real
accounts. Discovering a wrong limit in a staging dashboard is cheap;
discovering it in production is not.

### Setting it up

```bash
python manage.py migrate
python manage.py seed_saas --backfill   # starter plans + flags, and a
                                        # subscription for existing accounts
python manage.py createsuperuser        # a superuser holds every capability
```

Then open `/staff/` and add the rest of the team under **Portal access**.

Schedule `python manage.py prune_audit_log` alongside the other retention jobs.

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
- Run `python manage.py seed_saas --backfill` once so every account has a
  subscription, then check `/staff/operations/` — the health screen is a
  production-readiness checklist for exactly this list.
- Schedule `python manage.py prune_audit_log` to apply the audit retention
  window (`audit_retention_days`, 365 days by default).
- Set `STAFF_PORTAL_TRUST_X_FORWARDED_FOR=True` **only** if the proxy in front
  of the app overwrites `X-Forwarded-For`. Trusting it otherwise lets any caller
  forge the IP address recorded in the audit trail.
