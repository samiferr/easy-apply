# Use Case Group 04: Resume Parsing & Automated Profile Onboarding

## System Scope
The `resume` app enables candidates to upload existing resumes in multiple formats (PDF, DOCX, TXT). The system extracts raw text, submits it asynchronously to DeepSeek AI using structured JSON prompts, runs collision detection against the active profile, and presents an interactive checklist for selective importation.

---

## UC-04.1: Multi-Format Resume Upload & Quota Validation

- **Primary Actor:** Candidate
- **Supporting System:** `staffportal.services.quotas`, `resume.tasks.enqueue_resume_analysis`
- **Objective:** Securely upload a resume file and trigger background AI extraction without blocking the web request.

### Preconditions
1. Candidate is authenticated with an active profile.
2. User has sufficient quota under `UsageMetric.RESUME_IMPORT`.
3. System runtime setting `ai_features_enabled` is active.

### Main Success Scenario
1. Candidate navigates to `/resume/upload/` ([`resume:upload`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L20-L40)).
2. Candidate attaches a file (valid extensions: `.pdf`, `.docx`, `.txt`) and submits the form.
3. System verifies plan allowance via `quotas.blocked_message(request.user, UsageMetric.RESUME_IMPORT)`:
   - If blocked, displays localized error and cancels processing.
4. System creates a `resume.ResumeImport` record with status `pending`, saving the file to `resumes/profile_<id>/<filename>`.
5. System consumes 1 quota unit via `quotas.consume(user, UsageMetric.RESUME_IMPORT)`.
6. System starts background processing via `enqueue_resume_analysis(resume_import)`:
   - Creates an `AITask` record (`kind="resume_import"`).
   - Enqueues Celery task to the broker.
7. System redirects candidate immediately to the review page `/resume/<id>/review/` ([`resume:review`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L43-L92)).

### Alternative Flows
- **Quota Exhausted:**
  - Candidate sees: *"You've used all X of this month's resume imports. Your allowance resets at the start of your next billing period."*
- **Unsupported File Type:**
  - Form validation rejects with: *"Unsupported file extension. Allowed extensions are: pdf, docx, txt."*
- **Celery Broker Offline:**
  - `core.tasks.dispatch` catches connection exception, marks `AITask` failed with user-friendly message, preventing HTTP 500.

### Key Code References
- View: [`resume.views.ResumeUploadView`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L20)
- Task Dispatcher: [`resume.tasks.enqueue_resume_analysis`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/tasks.py)
- Model: [`resume.models.ResumeImport`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/models.py#L11)

---

## UC-04.2: Background Asynchronous Extraction via DeepSeek LLM

- **Primary Actor:** Background AI Worker
- **Supporting System:** `resume.services.extractor`, `resume.services.deepseek_resume`, DeepSeek API
- **Objective:** Parse document text and invoke LLM to produce structured profile JSON adhering to profile language.

### Main Success Scenario
1. Celery worker receives `parse_resume(resume_import_id, task_id)`.
2. Worker updates `AITask` to `running` with step *"Reading your resume"*.
3. Worker calls `resume.services.extractor.extract_text(file_path)`:
   - For PDF: uses `pypdf.PdfReader` to extract pages.
   - For DOCX: uses `docx.Document` to extract paragraph text.
   - For TXT: decodes UTF-8 text with fallback handling.
4. Worker saves raw text to `ResumeImport.raw_text`.
5. Worker invokes `resume.services.deepseek_resume.extract_resume_data(raw_text, language=profile.language)`:
   - Employs DeepSeek prompt instructing the LLM to format candidate experience, degrees, certificates, skills, and languages into rigid JSON schema conforming to `profile.language`.
6. DeepSeek returns structured JSON.
7. Worker validates JSON structure, saves to `ResumeImport.ai_response`, records `ai_model`, and updates `ResumeImport.status = "completed"`.
8. Worker marks `AITask` as `done` with redirect target set to review page.

### Alternative Flows
- **Unreadable / Empty Document:**
  - Task marks `ResumeImport.status = "failed"` with message: *"Could not extract readable text from this file."*
- **Transient AI Failure (Rate Limit / Timeout):**
  - Worker retries up to 3 times with exponential backoff (`5 * (2**retries)`).
- **Hard AI Error (Invalid API Key / Invalid Response):**
  - Task fails cleanly without retry, updating `error_message` on `AITask` and `ResumeImport`.

### Key Code References
- Task: [`resume.tasks.parse_resume`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/tasks.py)
- Extractor: [`resume.services.extractor`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/services/extractor.py)
- DeepSeek Client: [`resume.services.deepseek_resume`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/services/deepseek_resume.py)

---

## UC-04.3: Intelligent Collision & Duplicate Detection

- **Primary Actor:** Candidate
- **Supporting System:** `resume.services.importer.build_review_sections`
- **Objective:** Compare parsed resume items against existing candidate profile data to highlight duplicates and prevent clutter.

### Main Success Scenario
1. Candidate views review page `/resume/<id>/review/` ([`resume:review`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L43)).
2. If `ResumeImport.status == "completed"`, system runs `build_review_sections(resume_import, request.profile)`.
3. System categorizes parsed data into sections:
   - **Profile Info:** Compares headline, bio, location against existing `profile`.
   - **Technical Skills & Soft Skills:** Matches names case-insensitively against `UserSkill.objects.filter(profile=profile)`.
   - **Languages:** Matches against `UserLanguage.objects.filter(profile=profile)`.
   - **Work Experience:** Compares company name and job title against `WorkExperience`.
   - **Education Degrees:** Compares school name and degree title against `Degree`.
   - **Certifications:** Compares certification name against `Certificate`.
4. System annotates each parsed item with:
   - `is_duplicate` (True/False)
   - `checked_by_default` (True if new; False if duplicate)
5. UI renders items in a modern review table with status badges (*"New"* vs. *"Already in profile"*).

### Key Code References
- Service: [`resume.services.importer.build_review_sections`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/services/importer.py)
- Template: `resume/resume_review.html`

---

## UC-04.4: Interactive Review Checklist & Transactional Selective Import

- **Primary Actor:** Candidate
- **Supporting System:** `resume.services.importer.apply_selected`
- **Objective:** Selectively check or uncheck parsed items and commit them to the profile database atomically.

### Main Success Scenario
1. In the review UI, candidate toggles checkboxes for items they wish to import.
2. Candidate clicks *"Apply Selected to Profile"* (POST to `/resume/<id>/review/`).
3. System verifies that at least one item is checked.
4. System executes `apply_selected(resume_import, request.profile, selected_keys)` inside an atomic database transaction:
   - Updates `Profile` scalar fields (if selected).
   - Inserts selected skills, automatically mapping to existing `SkillCategory` or default category.
   - Inserts selected languages, linking to `languages.Language`.
   - Inserts selected work experiences along with their parsed highlight bullets.
   - Inserts degrees and certificates.
   - Sets `ResumeImport.status = "applied"` and records `applied_at = timezone.now()`.
5. System recalculates `profile.update_completion_percent()`.
6. System generates a flash message summarizing applied counts (e.g. *"Updated 8 skill(s), 2 work experience entries, 1 degree(s) from your resume."*).
7. System redirects candidate to their updated profile view ([`accounts:profile`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).

### Key Code References
- View: [`resume.views.ResumeReviewView.post`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/views.py#L65-L92)
- Service: [`resume.services.importer.apply_selected`](file:///home/sami/PycharmProjects/Github/easy-apply/resume/services/importer.py)
