# Use Case Group 07: Tailored Resume Authoring & PDF Export

## System Scope
The `resume` app enables candidates to author job-specific tailored resumes. Using the candidate's profile snapshot, the job requirements match analysis, and structured templates, DeepSeek AI synthesizes an optimized Markdown resume draft. Candidates can review and edit this draft directly in the browser and compile it into an ATS-friendly, beautifully formatted PDF via ReportLab.

---

## UC-07.1: AI Generation of Job-Tailored Resume Draft

- **Primary Actor:** Candidate / Background AI Worker
- **Supporting System:** `staffportal.services.quotas`, `resume.services.tailored`, `templates/resume_template.md`
- **Objective:** Generate a job-tailored resume draft highlighting the candidate's most relevant qualifications for a specific position.

### Preconditions
1. Job post status is `completed` (`job.status == JobPost.STATUS_COMPLETED`).
2. Candidate has sufficient quota for `UsageMetric.TAILORED_RESUME`.
3. System runtime setting `ai_features_enabled` is active.

### Main Success Scenario
1. From the job post detail page, candidate clicks *"Write tailored resume"*.
2. Browser issues POST to `/resume/tailored/<job_pk>/generate/` ([`resume:tailored_generate`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L104-L125)).
3. System checks quota via `quotas.blocked_message(request.user, UsageMetric.TAILORED_RESUME)`.
4. System retrieves or creates `resume.TailoredResume` (with `state="processing"`) linked to `job` and `request.profile`.
5. System consumes 1 quota unit via `quotas.consume`.
6. System enqueues background task `enqueue_tailored_resume(job)`:
   - Instantiates `AITask` (`kind="tailored_resume"`).
   - Celery worker executes `generate_tailored_resume`:
     a. Gathers full candidate snapshot via `core.utils.build_resume_snapshot(profile)`.
     b. Gathers job details and match evaluation (strong, partial, missing elements).
     c. Enforces profile language via `core.language.language_clause(profile.language)`.
     d. Loads base template structure `templates/resume_template.md`.
     e. Submits prompt to DeepSeek AI.
     f. AI synthesizes a tailored resume in Markdown, strategically emphasizing relevant accomplishments and matching keywords.
     g. Saves markdown output to `TailoredResume.markdown`, sets `ai_model`, and updates `TailoredResume.state = "completed"`.
     h. Marks `AITask` as `done`.
7. Web request redirects candidate to `/resume/tailored/<job_pk>/` ([`resume:tailored`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L128-L157)) where live progress is rendered until ready.

### Alternative Flows
- **Job Not Yet Analyzed:**
  - Candidate is redirected back to job page with warning: *"Analyze this job post first, then generate a resume for it."*
- **Quota Blocked:**
  - Request redirected with error banner explaining quota exhaustion or plan restrictions.

### Key Code References
- View: [`resume.views.TailoredResumeGenerateView`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L104)
- Service: [`resume.services.tailored.draft_tailored_resume`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/services/tailored.py)
- Model: [`resume.models.TailoredResume`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/models.py#L40)

---

## UC-07.2: Interactive Markdown In-Browser Editing & Modification Tracking

- **Primary Actor:** Candidate
- **Supporting System:** `resume.views.TailoredResumeEditView`, `TailoredResumeForm`
- **Objective:** Review, refine, and manually customize the AI-generated resume draft in a live Markdown editor.

### Main Success Scenario
1. Candidate navigates to `/resume/tailored/<job_pk>/`.
2. System displays the split/full Markdown editor containing the drafted resume text.
3. Candidate edits headings, refines achievement bullet points, adjusts summary, or updates contact details.
4. Candidate clicks *"Save changes"*.
5. System receives POST request:
   - Compares submitted text against previous content.
   - If changed, sets `TailoredResume.edited_by_user = True`.
   - Persists updated markdown to SQLite.
6. System displays confirmation message: *"Saved your changes."*

### Key Code References
- View: [`resume.views.TailoredResumeEditView.post`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L141-L157)
- Form: [`resume.forms.TailoredResumeForm`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/forms.py)

---

## UC-07.3: ReportLab PDF Compilation with Strict Language Formatting

- **Primary Actor:** Candidate
- **Supporting System:** `resume.services.pdf.render_markdown_pdf`, ReportLab engine
- **Objective:** Compile the Markdown resume into an ATS-friendly, clean, high-resolution PDF document.

### Main Success Scenario
1. Candidate clicks *"Download PDF"* from the tailored resume screen (or selects action `"pdf"` from the editor form).
2. Request hits `/resume/tailored/<job_pk>/pdf/` ([`resume:tailored_pdf`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L160-L165)).
3. System calls `tailored_resume_pdf_response(tailored_resume)`:
   - System invokes `resume.services.pdf.render_markdown_pdf(markdown_text, title=job.title, author=full_name)`.
   - Parses Markdown AST into ReportLab `Flowable` components:
     - Header block (Full name in primary bold typography, contact info separated by bullets).
     - Section headings (`#`, `##`) with underline accents and proportional vertical spacing.
     - Formatted dates, italicized subheaders, and bullet lists with tight margins.
   - Configures PDF canvas: standard Letter/A4 page sizing, font family fallbacks (Helvetica, Times, DejaVu for UTF-8 coverage), page numbering.
   - Compiles document to binary bytes stream.
4. System sets response headers:
   - `Content-Type: application/pdf`
   - `Content-Disposition: attachment; filename="<slug>-resume.pdf"` (e.g. `sami-ferr-google-lead-engineer-resume.pdf`).
5. Browser triggers download of the compiled PDF.

### Alternative Flows
- **PDF Compilation Error:**
  - If malformed Markdown tokens occur, PDF engine sanitizes invalid XML entities and formats plain text blocks safely.

### Key Code References
- View / Handler: [`resume.views.tailored_resume_pdf_response`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L203-L211)
- PDF Engine: [`resume.services.pdf.render_markdown_pdf`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/services/pdf.py)

---

## UC-07.4: Raw Markdown Export & Tailored Resume Lifecycle

- **Primary Actor:** Candidate
- **Objective:** Download the raw Markdown document for external tools or delete obsolete drafts.

### Main Success Scenario (Markdown Download)
1. Candidate clicks *"Download .md"*.
2. System responds from `/resume/tailored/<job_pk>/markdown/` with `Content-Type: text/markdown; charset=utf-8` and attachment filename (e.g. `sami-ferr-google-lead-engineer-resume.md`).

### Main Success Scenario (Deletion)
1. Candidate navigates to `/resume/tailored/<job_pk>/delete/` ([`resume:tailored_delete`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L176-L200)).
2. System displays confirmation modal.
3. Candidate confirms deletion (POST).
4. System deletes `TailoredResume` row; the associated `JobPost` remains intact.
5. Candidate is redirected to `/jobs/<job_pk>/` with notification: *"Deleted the tailored resume for this job."*

### Key Code References
- Views: [`resume.views.TailoredResumeMarkdownView`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L168), [`resume.views.TailoredResumeDeleteView`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L176)
