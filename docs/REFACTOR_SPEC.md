# Easy Apply — Deep Refactoring Spec

> Paste this whole document as the prompt for the refactor. It is written against
> the code as it exists on `main` at the time of writing; every "today" statement
> below was verified in the repo.

---

## 0. Context you must respect

**Stack (do not change):** Django 5 · SQLite · Tailwind CSS 3 (CLI build) ·
Alpine.js · WhiteNoise · DeepSeek chat-completions in JSON mode via
`core/ai.py::call_deepseek_json`. No Celery, no Redis, no HTMX, no Node runtime
in production (`static/dist/output.css` is committed).

**Must keep working, re-skinned but not re-architected:**
resume import (`resume/services/importer.py`), tailored resume + PDF export
(`resume/services/tailored.py`, `pdf.py`), the Markdown recap export
(`core/utils.py::generate_markdown_recap`), and the whole auth/password-reset flow.

**Rebuild `npm run build` after any Tailwind class changes** — new classes that
never appear in a template will be purged.

---

## 1. Theme & layout

### 1.1 Blue theme
Replace the teal `brand` scale in `tailwind.config.js` with blue:

```js
brand: {
  50:"#eff6ff", 100:"#dbeafe", 200:"#bfdbfe", 300:"#93c5fd", 400:"#60a5fa",
  500:"#3b82f6", 600:"#2563eb", 700:"#1d4ed8", 800:"#1e40af", 900:"#1e3a8a",
  950:"#172554",
}
```

Keep dark mode (`darkMode: "class"`). Every new component needs `dark:` variants.
Move the theme toggle **out of the top bar and into the user dropdown**.

### 1.2 Two base templates
Split `templates/base.html` into:

- **`templates/base_public.html`** — marketing page, legal pages, auth screens.
  Centered top nav + full footer. No sidebar.
- **`templates/base_app.html`** — every authenticated screen. Fixed left sidebar +
  top bar. Keep the existing toast/messages block and the skip-to-content link in
  both.

**Sidebar** (`templates/partials/sidebar.html`) — collapsible on desktop
(persist collapsed state in `localStorage`), off-canvas drawer under `md:`:

```
Dashboard
Jobs          → Job list · Analyze a job post
Profile       → Job preferences · Experience · Education · Technical skills
                · Soft skills · Languages
Resume        → Import from resume · Tailored resumes
```

Mark the active item from `request.resolver_match` (app_name + view_name), the way
the current navbar already does.

**Top bar** (`templates/partials/topbar.html`), left → right:
brand mark + wordmark · *(spacer)* · **language switcher (FR / EN)** · **user menu**.
User menu contains: Personal info, Security, Theme toggle, Export recap (.md),
Admin (staff only), Log out.

---

## 2. Internationalization (FR / EN) — full pass

Today `USE_I18N = True` but there is **no `LocaleMiddleware`, no `LOCALE_PATHS`, and
not one `{% trans %}` tag in ~40 templates**. Wire it end to end:

1. `config/settings.py`: `LANGUAGE_CODE = "en"`,
   `LANGUAGES = [("en", "English"), ("fr", "Français")]`,
   `LOCALE_PATHS = [BASE_DIR / "locale"]`.
2. `MIDDLEWARE`: insert `django.middleware.locale.LocaleMiddleware`
   **after** `SessionMiddleware`, **before** `CommonMiddleware`.
3. `config/urls.py`: add `path("i18n/", include("django.conf.urls.i18n"))`.
   The switcher is a POST form to `set_language` carrying `next` — **use the cookie
   approach, not `i18n_patterns`**, so no existing URL name or reverse() breaks.
4. Wrap **every** user-facing string: templates (`{% trans %}` / `{% blocktrans %}`),
   model `verbose_name`/`help_text`/choice labels, form labels and errors, view
   `messages.*` calls, and the section/tab labels in §3.
5. `django-admin makemessages -l fr` then **fill `locale/fr/LC_MESSAGES/django.po`
   completely** and compile it. A `fuzzy` or empty msgstr is not done.
6. **AI output language:** pass the active language into every system prompt so
   summaries, match evidence and extracted section labels come back in the user's
   language. Store it on `JobPost` (`analysis_language`) so a re-render does not
   silently mix languages.

---

## 3. Job analysis — fixed sections

### 3.1 The section list is a closed enum

Today `RequirementCategory.name` is a free-text string the AI invents, typed only
as `responsibilities | required | preferred | other`. **Replace this with a fixed,
ordered enum.** The AI may never create a section outside it; the importer must
discard anything unrecognized.

Create `jobs/sections.py` as the single source of truth:

| # | `key` | Label | Rows? | Matched against |
|---|---|---|---|---|
| 1 | `overview` | Overview | no | — |
| 2 | `company` | Company | no | — |
| 3 | `location_arrangement` | Location & work arrangement | **yes** | Job preferences |
| 4 | `compensation_benefits` | Compensation & benefits | **yes** | Job preferences |
| 5 | `how_to_apply` | How to Apply | no | — |
| 6 | `responsibilities` | Responsibilities | **yes** | Experience + Technical skills |
| 7 | `required_technical_skills` | Required Technical Skills | **yes** | Technical skills |
| 8 | `desirable_technical_skills` | Desirable Technical Skills | **yes** | Technical skills |
| 9 | `desirable_soft_skills` | Desirable Soft Skills | **yes** | Soft skills |
| 10 | `languages` | Languages | **yes** | Languages |
| 11 | `education_certifications` | Education & Certifications | **yes** | Education (degrees + certificates) |
| 12 | `worth_noting` | Worth noting | no | — |
| 13 | `red_flags` | Possible red flags | no | — |

Notes on this table:
- Sections 11 (Education & Certifications) is an **addition to the original strict
  list**, requested explicitly — the app already has an `education` app that resume
  import and the tailored-resume generator both depend on.
- "Worth noting" and "Possible red flags" are **two separate sections**, not one.
- Non-matched sections render as read-only prose/detail blocks — no match table, no
  tags, no add-to-profile button.
- **No section outside this list may ever be created.**

### 3.2 Sections 3 and 4 become rows

`location`, `work_arrangement`, `timezone_expectations`, `relocation_offered`,
`travel_percentage`, `salary_*`, `compensation_notes` and `benefits` are scalar
fields on `JobPost` today. Keep the scalars (the job list card and tailored-resume
generator read them), but **additionally** have the analyzer emit each as atomic,
evaluable rows so they can carry a match tag and an add-to-profile button:

- `location_arrangement` → `"Hybrid — 3 days on-site in Montréal"`, `"Up to 20% travel"`, `"EST ±2h overlap"`
- `compensation_benefits` → `"$120,000–$140,000 CAD / year"`, `"Health insurance"`, `"Dental care"`, `"4 weeks PTO"`

### 3.3 Model changes (`jobs/models.py`)

```python
class JobSection(models.Model):        # renamed from RequirementCategory
    job          = FK(JobPost, related_name="sections")
    key          = CharField(choices=SECTION_CHOICES)   # from jobs/sections.py
    order        = PositiveSmallIntegerField()          # index in the fixed list
    body         = TextField(blank=True)                # prose for non-row sections
    match_state  = CharField(choices=[idle, running, done, failed], default="idle")
    matched_at   = DateTimeField(null=True, blank=True)
    class Meta: constraints = [UniqueConstraint(fields=["job","key"], ...)]

class JobElement(models.Model):        # renamed from Requirement
    section        = FK(JobSection, related_name="elements")
    text           = TextField()
    order          = PositiveSmallIntegerField(default=0)
    match_status   = CharField(choices=[strong, partial, none], blank=True)
    match_evidence = TextField(blank=True)
    evaluated_at   = DateTimeField(null=True, blank=True)
    added_to_profile_at = DateTimeField(null=True, blank=True)
```

Rename `Requirement`/`RequirementCategory` throughout; keep
`JobPost.requirement_match_summary()` but retarget it at `JobElement` and count
only rows in matched sections.

### 3.4 Migration of existing data
**Wipe and force re-analysis** (explicitly chosen). A data migration deletes every
`RequirementCategory` row (cascading to `Requirement`), sets `analyzed_at = None`
and `status = pending` on every `JobPost`. The detail page shows a
"Re-analyze this job to get the new section breakdown" banner for any completed-but-
section-less job.

### 3.5 Analysis page UI (`templates/jobs/job_detail.html`)

Full-width, **left vertical tab rail** listing all 13 sections; content pane on the
right. Each rail item shows the section label, its element count, and a compact
match indicator (green/amber/grey dots, or a spinner while `match_state == running`).
Persist the selected tab in the URL hash so a reload keeps your place.

Matched sections render a **table**, one row per element:

| Requirement | Match | Analysis | Action |
|---|---|---|---|
| element text | tag: Strong / Partial / Not covered | one-sentence evidence | **Add to my profile** |

---

## 4. Per-element "Add to my profile"

Clicking **Add to my profile** on a row:

1. `GET /jobs/<pk>/elements/<el_id>/add/` returns a **rendered HTML modal fragment**
   containing a real Django form, pre-filled from the element text. Alpine injects
   it with `x-html` — this keeps form markup in templates instead of duplicating it
   in JS.
2. The user **reviews and edits** the pre-filled values, then submits.
3. `POST` to the same URL creates the profile object, stamps
   `element.added_to_profile_at`, then **re-evaluates that one element only** and
   returns JSON: `{ "ok": true, "row_html": "...", "summary": {...} }`.
4. Alpine swaps the row and updates the section + job match meters. **Nothing else
   is re-evaluated and no full page reload happens.**

The per-section target is a registry in `jobs/sections.py`, so adding a section
later means one dict entry, not a chain of `if` branches:

| Section | Creates |
|---|---|
| `required_technical_skills`, `desirable_technical_skills` | `UserSkill` (category kind `technical`) |
| `desirable_soft_skills` | `UserSkill` (kind `soft`) |
| `languages` | `UserLanguage` (+ `Language` get_or_create) |
| `responsibilities` | `ExperienceHighlight` on a `WorkExperience` the user picks in the modal |
| `education_certifications` | `Degree` **or** `Certificate` (modal lets the user choose) |
| `location_arrangement` | `JobPreference` scalar fields |
| `compensation_benefits` | `BenefitPreference` row, or `JobPreference` salary fields |

Guard every handler: reject duplicates against existing `UniqueConstraint`s and
show the conflict in the modal rather than 500-ing.

---

## 5. Profile

Left vertical tab rail, same shell as §3.5. Tabs, in order:

1. **Job preferences** *(new)*
2. **Experience**
3. **Education & Certifications**
4. **Technical Skills**
5. **Soft Skills**
6. **Languages**

Keep **Personal info** (`accounts:profile` — headline, bio, avatar, contact links)
and **Security** as two further items in the same rail; they have to live somewhere
and are already built. *(Flag if you would rather they stayed only in the user menu.)*

### 5.1 New app: `preferences`

```python
class JobPreference(models.Model):          # OneToOne with User
    # Compensation
    desired_salary_min / desired_salary_max / salary_currency / salary_period
    # Location & arrangement
    preferred_locations      = TextField(blank=True)   # one per line
    remote_ok / hybrid_ok / onsite_ok = BooleanField(default=False)
    max_onsite_days_per_week = PositiveSmallIntegerField(null=True, blank=True)
    willing_to_relocate      = BooleanField(null=True, blank=True)
    max_travel_percentage    = PositiveSmallIntegerField(null=True, blank=True)
    timezone_preference      = CharField(blank=True)
    employment_types         = CharField(blank=True)   # reuse WorkExperience choices
    availability_notes       = TextField(blank=True)
    updated_at               = DateTimeField(auto_now=True)

class BenefitPreference(models.Model):
    IMPORTANCE = [("must_have","Must have"), ("nice_to_have","Nice to have"),
                  ("not_important","Not important")]
    preference = FK(JobPreference, related_name="benefits")
    name       = CharField(max_length=120)      # "Health benefits", "Dental care", ...
    importance = CharField(choices=IMPORTANCE, default="nice_to_have")
    notes      = CharField(max_length=250, blank=True)
```

Seed a starter benefit list on first visit (Health benefits, Dental care, Vision
care, Life insurance, Retirement / pension matching, Paid time off, Parental leave,
Professional development budget, Flexible hours, Equity / stock options, Remote work
stipend, Wellness / gym) all defaulting to `nice_to_have`, so the tab is never empty.

---

## 6. AI optimization — scoped, per-section matching

This is the core efficiency change. Today `jobs/services/matcher.py` sends **every
requirement plus the entire profile snapshot in one call**.

### 6.1 Scoped profile slices
Add `build_profile_slice(user, section_key)` to `core/utils.py` that returns
**only** the mapped part of the profile:

```
location_arrangement       → job preferences (location + arrangement fields)
compensation_benefits      → job preferences (salary + benefits)
responsibilities           → experience (with highlights) + technical skills
required_technical_skills  → technical skills
desirable_technical_skills → technical skills
desirable_soft_skills      → soft skills
languages                  → languages
education_certifications   → degrees + certificates
```

Nothing else may be sent. Keep `build_profile_snapshot` for the tailored-resume
path, which legitimately needs everything.

### 6.2 Short-circuit empty slices
If a slice is empty, **do not call the API**. Mark every element in that section
`none` with evidence like "No languages recorded in your profile yet" and link to the
matching profile tab. This saves a call per empty section.

### 6.3 Execution model — progressive
1. **On submit:** one inline extraction call (`analyze_job_text`) that returns all
   13 sections at once. Job goes `completed`; all sections exist with
   `match_state = "idle"`. This is the only AI call in the request cycle.
2. **On the analysis page:** Alpine fires one `fetch` per matched section to
   `POST /jobs/<pk>/sections/<key>/match/`, at most 2–3 concurrent. Each tab shows a
   spinner, then fills in. A failed section shows a **Retry** button — it never
   poisons the others.
3. **Per element:** `POST /jobs/<pk>/elements/<el_id>/match/` re-evaluates one row.

Set `section.match_state` around each call so a reload mid-run is never ambiguous.
No request should ever hold more than one AI call.

### 6.4 Prompts
Split `jobs/services/deepseek_client.py`:
- **Extraction prompt** — returns the 13 fixed sections keyed by `key`, prose in
  `body` for non-row sections, atomic one-idea-per-item strings in `elements` for row
  sections, in the active language. Keep the existing "never invent facts, use empty
  string/null" rules.
- **Per-section match prompt** — receives `{section_key, section_label, elements[], profile_slice}`
  only. Same `strong | partial | none` verdicts and one-sentence, evidence-naming
  explanations as the current matcher, which is good and should be preserved.
- **Single-element match prompt** — same, with one element.

Keep the defensive parsing style of `jobs/services/importer.py` (`_clean_str`,
`_clean_int`, `_clean_list`) — the AI response is never trusted.

---

## 7. Marketing page (`templates/core/home.html`)

Public, `base_public.html`, large display-scale headings.

1. **Hero** — headline, subhead, primary CTA **Create your account**, secondary
   "Log in". One product visual.
2. **Steps** — three numbered cards with connectors:
   `Upload your resume → Paste a job post → Get your tailored resume`
3. **Why** — 4–6 benefit cards (per-requirement matching, one-click add to profile,
   red-flag detection, tailored resume + PDF, bilingual, your data stays yours).
4. **Final CTA** band.
5. **Footer** — product links, and the legal links from §9.

Fully translated FR/EN. Must look right at 375px.

---

## 8. Dashboard (`templates/core/dashboard.html`)

Replace the current stat-tiles + checklist page with:

1. **Quick links** — Analyze a job post · Import a resume · Complete my profile ·
   Job preferences. Large icon cards.
2. **Last analyzed jobs** — 5 most recent `JobPost`s: title, company, status badge,
   match score meter, relative date, link.
3. **Jobs analyzed — bar chart**, current month, one bar per day.
   Aggregate server-side with
   `JobPost.objects.filter(user=..., created_at__month=...).annotate(day=TruncDate(...)).values("day").annotate(n=Count("id"))`,
   then render as a **server-side SVG/CSS bar chart — do not add a JS charting
   library.** Label axes, handle the all-zeros month, and give it `dark:` variants
   and an accessible `<table class="sr-only">` fallback.
4. Keep the profile-completion meter, compacted into the sidebar of this page.

---

## 9. Legal pages

New `legal` app (or `core` routes) with real, complete content in **both FR and EN**:

- Privacy Policy · Terms of Service · Cookie Policy · Mentions légales / Legal notice · Contact

Entity-specific details (legal name, registered address, jurisdiction, hosting
provider, DPO contact) go in as **clearly marked `TODO:` placeholders**, pulled from
settings constants so they are filled in one place.

The content must actually cover what this app does:
- Resume files are uploaded and stored (`media/resumes/user_<id>/`) — say what, how
  long, and how to delete.
- **Job text, resume text and profile data are sent to DeepSeek, a third-party AI
  processor** — name it as a sub-processor and say data leaves the user's region.
- Cookies in use: session, CSRF, `django_language`, and the `localStorage` theme /
  sidebar keys.
- GDPR rights: access, rectification, erasure (the account-deletion flow on
  `accounts:security` already exists — link it), portability (the Markdown recap
  export already exists — link it).

Link all of these from the public footer and from the app footer.

---

## 10. Jobs list (`templates/jobs/job_list.html`)

Full-width **card list** (one card per row, not a grid of tiles), large headings.
Each card: job title (display size), company · seniority, status badge, work-
arrangement badge, salary range, match-score meter with strong/partial/none counts,
analyzed date, and row actions (Open, Tailored resume, Re-analyze, Delete).
Add a search box, a status filter, and empty/loading states.

---

## 11. Definition of done

- [ ] `python manage.py makemigrations --check` clean; `migrate` runs on a fresh DB **and** on a copy of the old one.
- [ ] `python manage.py check` and the existing test suite pass.
- [ ] No `RequirementCategory` / `Requirement` references remain anywhere.
- [ ] The analyzer cannot produce a section outside the 13 keys — verify with a test that feeds it a junk section.
- [ ] Each match call's payload contains **only** the mapped profile slice — verify with a test asserting an unmapped key is absent.
- [ ] Empty slices short-circuit without an HTTP call.
- [ ] Add-to-profile creates the right object, re-evaluates exactly one element, and updates the row without a page reload.
- [ ] `django-admin compilemessages` produces no fuzzy/empty FR strings; switching to FR translates every screen including the legals.
- [ ] `npm run build` regenerated and `static/dist/output.css` committed.
- [ ] Every screen works at 375px; sidebar collapses to a drawer.
- [ ] Light and dark both look right on every new component.
- [ ] Resume import, tailored resume + PDF, and Markdown recap all still work.

## 12. Suggested commit sequence

1. Theme + `base_app`/`base_public` split + sidebar/topbar shell
2. i18n wiring + language switcher (catalogue filled last, once strings settle)
3. `jobs/sections.py` + model rename + wipe migration
4. New extraction prompt + importer rewrite
5. Scoped slices + per-section/per-element matchers + JSON endpoints
6. `preferences` app + profile tab rail
7. Job analysis page (tab rail, tables, add-to-profile modal)
8. Dashboard + jobs list
9. Marketing page + legal pages
10. FR catalogue, `npm run build`, README update
