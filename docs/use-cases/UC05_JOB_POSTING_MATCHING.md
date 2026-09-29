# Use Case Group 05: Job Posting Ingestion & Scoped Semantic Matching

## System Scope
The `jobs` app handles the ingestion, extraction, and evaluation of external job postings. It decomposes messy job postings into 13 canonical sections, feeds targeted profile slices into DeepSeek AI, evaluates coverage per requirement element, and supports fault-tolerant parallel matching through Celery chords.

---

## UC-05.1: Job Posting Creation & Allowance Verification

- **Primary Actor:** Candidate
- **Supporting System:** `staffportal.domain.quotas`, `jobs.tasks.enqueue_job_analysis`
- **Objective:** Submit raw job posting text and initiate the background analysis pipeline.

### Preconditions
1. Candidate is authenticated with an active profile.
2. User's monthly quota for `UsageMetric.JOB_ANALYSIS` has not been exceeded.
3. System runtime setting `ai_features_enabled` is active.

### Main Success Scenario
1. Candidate navigates to `/jobs/new/` ([`jobs:create`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L42-L73)).
2. Candidate pastes the full text of a job posting (and optionally inputs initial title/company if known).
3. Candidate submits the form (POST).
4. System verifies quota via `quotas.blocked_message(request.user, UsageMetric.JOB_ANALYSIS)`:
   - If blocked, execution stops and the pasted text is preserved in the form.
5. System creates `JobPost` with `status="pending"` linked to `request.profile`.
6. System calls `quotas.consume(request.user, UsageMetric.JOB_ANALYSIS)`.
7. System enqueues Celery workflow via `enqueue_job_analysis(job_post)`:
   - Instantiates `AITask` (`kind="job_analysis"`).
   - Prepares Celery chain: `read_job_text -> extract_job_sections -> _dispatch_section_matches`.
8. Candidate is redirected immediately to the job detail screen `/jobs/<id>/` ([`jobs:detail`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L75-L101)).

### Key Code References
- View: [`jobs.views.JobPostCreateView`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L42)
- Task Workflow: [`jobs.tasks.enqueue_job_analysis`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L182-L203)
- Models: [`jobs.models.JobPost`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/models.py)

---

## UC-05.2: 13-Section Deep Extraction Pipeline (Celery Chain)

- **Primary Actor:** Background AI Worker
- **Supporting System:** `jobs.domain.deepseek_client.analyze_job_text`, `jobs.sections.SECTIONS`
- **Objective:** Parse raw job text into 13 canonical sections with classified elements in the profile's language.

### Main Success Scenario
1. Step 1: Worker executes `read_job_text(job_id, task_id)`:
   - Verifies text content; updates `JobPost.status = "processing"`.
2. Step 2: Worker executes `extract_job_sections`:
   - Retrieves `language = job.profile.language`.
   - Calls `analyze_job_text(raw_text, language=language)`: DeepSeek maps text into 13 rigid sections:
     1. `overview` (prose)
     2. `company` (prose)
     3. `location_arrangement` (matched rows)
     4. `compensation_benefits` (matched rows)
     5. `how_to_apply` (prose)
     6. `responsibilities` (matched rows)
     7. `required_technical_skills` (matched rows)
     8. `desirable_technical_skills` (matched rows)
     9. `desirable_soft_skills` (matched rows)
     10. `languages` (matched rows)
     11. `education_certifications` (matched rows)
     12. `worth_noting` (prose)
     13. `red_flags` (prose)
   - Calls `jobs.domain.importer.apply_analysis`: Creates `JobSection` rows and child `JobElement` rows in SQLite.
3. System updates `JobPost.title` and `company_name` from extracted metadata.
4. Celery chain hands off section IDs to `_dispatch_section_matches`.

### Key Code References
- Tasks: [`jobs.tasks.read_job_text`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L30), [`jobs.tasks.extract_job_sections`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L60)
- Section Registry: [`jobs.sections.SECTIONS`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/sections.py)

---

## UC-05.3: Scoped Profile Slice Matching (Celery Chord Fan-Out)

- **Primary Actor:** Background AI Worker
- **Supporting System:** `jobs.domain.matcher.match_section_to_profile`, `core.services.build_profile_slice`
- **Objective:** Match each extracted section in parallel using ONLY relevant parts of the candidate profile.

### Main Success Scenario
1. Task `_dispatch_section_matches` identifies all sections flagged `is_matched=True` that contain elements.
2. It constructs a Celery `chord`:
   ```python
   chord(
       group(match_job_section.s(sid, task_id) for sid in section_ids),
       finalize_job_analysis.s(job_id, task_id)
   )
   ```
3. In parallel, Celery workers execute `match_job_section`:
   - Builds targeted profile slice via `build_profile_slice(job.profile, section.key)`:
     - e.g. For `required_technical_skills`: returns `{ "technical_skills": [...] }`.
     - e.g. For `location_arrangement`: returns `{ "preferred_locations": [...], "acceptable_work_arrangements": [...] }`.
   - Passes elements and slice into DeepSeek prompt.
   - For each `JobElement`, DeepSeek assigns:
     - `match_level`: `strong`, `partial`, or `none`.
     - `evidence`: Concise explanation in `profile.language` citing specific profile facts.
   - Worker persists match levels and evidence to `JobElement` records.
   - Sets `JobSection.match_state = "completed"`.
4. `finalize_job_analysis` gathers results, updates overall job match stats, and marks `AITask` as `done`.

### Key Code References
- Dispatcher: [`jobs.tasks._dispatch_section_matches`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L206-L225)
- Matching Task: [`jobs.tasks.match_job_section`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L112-L152)
- Slice Builder: [`core.services.build_profile_slice`](file:///home/sami/PycharmProjects/Github/easy-apply/core/services.py#L324-L352)

---

## UC-05.4: Zero-Cost Empty Slice Handling

- **Primary Actor:** Background AI Worker
- **Supporting System:** `core.services.profile_slice_is_empty`, `core.services.empty_slice_hint`
- **Objective:** Eliminate redundant AI API calls when the candidate has not yet recorded the relevant slice data.

### Main Success Scenario
1. Worker enters `match_section_to_profile(section)`.
2. System retrieves `slice_data = build_profile_slice(profile, section.key)`.
3. System checks `profile_slice_is_empty(slice_data)`.
4. If the slice contains no candidate data (e.g., candidate has 0 technical skills recorded):
   - System **bypasses DeepSeek AI entirely**.
   - Retrieves localized explanation from `empty_slice_hint(section.key)` (e.g. *"No technical skills recorded in your profile yet."*).
   - In a single bulk update, marks all child `JobElement` rows as `match_level="none"` and populates the hint into `evidence`.
   - Sets `JobSection.match_state = "completed"`.
5. Operation completes in sub-millisecond local DB query without consuming API quota or tokens.

### Key Code References
- Matcher Logic: [`jobs.domain.matcher.match_section_to_profile`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/domain/matcher.py)
- Utility: [`core.services.profile_slice_is_empty`](file:///home/sami/PycharmProjects/Github/easy-apply/core/services.py#L355-L368)

---

## UC-05.5: Non-Poisoning Fault Isolation & Per-Section Tab Retries

- **Primary Actor:** Candidate / Background AI Worker
- **Supporting System:** `jobs.views.JobSectionRematchView`, `jobs.tasks.enqueue_section_match`
- **Objective:** Prevent one transient API error in a single section from halting the entire job analysis, and allow on-demand section retries.

### Main Success Scenario
1. Suppose DeepSeek times out when evaluating the `desirable_soft_skills` section during the chord.
2. `match_job_section` catches `AIServiceError` after retry exhaustion:
   - Sets `JobSection.match_state = "failed"` and writes `match_error`.
   - Returns normally `{ "ok": False, "section_id": ... }` to the chord header instead of raising an unhandled exception.
3. `finalize_job_analysis` receives normal completion for the other 12 sections:
   - Successfully completes the job match.
4. On the UI detail page, candidate views all working sections. The failing tab displays an alert: *"This section failed to match: [error message]"* with a *"Retry this section"* button.
5. Candidate clicks *"Retry"*:
   - Submits POST to `/jobs/<pk>/sections/<sec_pk>/rematch/` ([`jobs:section_rematch`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L143-L162)).
   - System enqueues an isolated `AITask` for that single section without re-billing.
   - Upon completion, section panel updates dynamically via AJAX or page refresh.

### Key Code References
- Section Retry View: [`jobs.views.JobSectionRematchView`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L143)
- Task: [`jobs.tasks.enqueue_section_match`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L228-L245)

---

## UC-05.6: Real-Time Unified State Polling (`/state/` API Contract)

- **Primary Actor:** Candidate (Browser / Alpine.js)
- **Supporting System:** `jobs.views.JobAnalysisStateView`
- **Objective:** Provide a single lightweight JSON polling endpoint to update the sidebar rail, match badges, and overall status without 13 independent HTTP queries.

### Main Success Scenario
1. While job analysis or matching is running, Alpine.js in `job_detail.html` polls `GET /jobs/<pk>/state/` every 2 seconds (with exponential backoff to 5 seconds).
2. Server executes `JobAnalysisStateView`:
   - Returns aggregated JSON containing `job_status`, `is_running`, `task_id`, `summary` (total strong, partial, none), and an array of all section states and counts.
3. Front-end dynamically updates the navigation rail:
   - Shows spinner next to active sections.
   - Updates match breakdown badges (`strong`, `partial`, `none`).
4. Once `is_running` becomes `False`, front-end halts polling and reveals completed action buttons (e.g. *"Write Tailored Resume"*).

### Key Code References
- View: [`jobs.views.JobAnalysisStateView`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L173-L215)
- Template: `templates/jobs/job_detail.html`

---

## UC-05.7: Full Job Re-Analysis vs. Profile Re-Match

- **Primary Actor:** Candidate
- **Supporting System:** `JobPostReanalyzeView` vs. `JobPostMatchProfileView`
- **Objective:** Distinguish between a costly re-extraction from scratch versus a free re-evaluation against an updated candidate profile.

### Main Success Scenario (Re-Match Against Profile - Free)
1. Candidate updates their profile (e.g., adds 5 new technical skills).
2. Candidate visits previously analyzed job post and clicks *"Re-match with profile"*.
3. System hits `POST /jobs/<pk>/match/` ([`jobs:match`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L123-L141)).
4. Since job structure is already extracted, this operation **does NOT consume monthly Job Analysis quota**.
5. System re-runs matching across all matched sections in parallel against the newly updated profile data.

### Alternative Scenario (Full Re-Analyze - Metered)
1. Candidate clicks *"Re-analyze job post"* ([`jobs:reanalyze`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L108-L121)).
2. Because this executes a fresh AI extraction trip, system validates quota via `quotas.blocked_message` and consumes 1 quota unit via `quotas.consume`.
3. Re-runs extraction from raw text.
