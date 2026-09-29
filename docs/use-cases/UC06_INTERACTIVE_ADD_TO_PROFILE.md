# Use Case Group 06: Interactive Requirement Gap-Closing ("Add to Profile")

## System Scope
When an analyzed job requirement is flagged as missing or partial (`match_level="none"` or `"partial"`), Easy Apply empowers the candidate to bridge the qualification gap immediately from the job details page. Using the `jobs.profile_targets` registry, an element spawns a targeted modal form pre-filled with the requirement data, saves it into the candidate's profile, and immediately triggers an asynchronous re-evaluation of that single element.

---

## UC-06.1: Missing Element Detection & Modal Form Rendering

- **Primary Actor:** Candidate
- **Supporting System:** `jobs.profile_targets.get_add_target`, `jobs.views.JobElementAddToProfileView`
- **Implemented by:** `jobs.services.profile_elements`, `jobs.services.add_target_for`, `jobs.services.can_add_to_profile`, `jobs.services.add_to_profile_form`
- **Objective:** Open an interactive modal dialog allowing the candidate to add an unfulfilled job requirement to their profile.

### Preconditions
1. Candidate is viewing a job post detail screen (`JobPostDetailView`).
2. The requirement element belongs to a section registered with an `AddTarget` (e.g. Technical Skills, Soft Skills, Languages, Responsibilities, Education/Certifications, Compensation/Benefits, Location/Arrangement).

### Main Success Scenario
1. In the job requirements table, candidate spots a requirement with a `"none"` or `"partial"` badge (e.g. *"Experience with Redis caching"*).
2. An *"Add to my profile"* button appears alongside the requirement.
3. Candidate clicks *"Add to my profile"*.
4. Alpine.js issues an AJAX `GET /jobs/<pk>/elements/<elem_pk>/add/` to `JobElementAddToProfileView`.
5. Server resolves `target = get_add_target(element.section.key)`:
   - For `required_technical_skills`: resolves to `SkillAddForm`.
   - For `desirable_soft_skills`: resolves to `SoftSkillAddForm`.
   - For `languages`: resolves to `LanguageAddForm`.
   - For `responsibilities`: resolves to `ExperienceHighlightAddForm`.
   - For `education_certifications`: resolves to `EducationAddForm`.
   - For `compensation_benefits`: resolves to `BenefitAddForm`.
   - For `location_arrangement`: resolves to `LocationPreferenceAddForm`.
6. System executes `target.initial_for(element)`, pre-populating fields:
   - e.g. Sets `name="Redis"` from `element.content`.
7. System renders `jobs/_add_to_profile_modal.html` and returns JSON `{ "ok": True, "modal_html": "..." }`.
8. Browser injects HTML into the DOM and displays the modal.

### Alternative Flows
- **Unsupported Section:**
  - If section key is not in `TARGETS` (e.g., prose overview or red flags), endpoint returns HTTP 400: *"This section can't be added to your profile."*

### Key Code References
- Registry & Forms: [`jobs.profile_targets`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/profile_targets.py)
- View: [`jobs.views.JobElementAddToProfileView.get`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L236-L260)

---

## UC-06.2: Contextual Form Pre-filling & Dynamic Target Mapping

- **Primary Actor:** Candidate
- **Supporting System:** Form validation & uniqueness constraints
- **Implemented by:** `jobs.services.add_to_profile_form`
- **Objective:** Review and adjust pre-filled requirement attributes before committing them to the permanent profile.

### Main Success Scenario
1. Candidate reviews the modal inputs:
   - **For Technical / Soft Skills:** Name is pre-filled. Candidate chooses proficiency level (Beginner, Intermediate, Advanced, Expert) and category.
   - **For Languages:** Name is pre-filled. Candidate selects proficiency level.
   - **For Responsibilities:** Highlight text is pre-filled. Candidate selects which of their existing `WorkExperience` entries this achievement belongs to.
   - **For Education / Certification:** Pre-fills credential or degree name; candidate selects whether it is an Academic Degree or Industry Certification.
   - **For Benefits:** Pre-fills benefit title; candidate chooses importance (`must_have` vs `nice_to_have`).
   - **For Location:** Pre-fills location string or arrangement flags (remote/hybrid).
2. Candidate makes adjustments and clicks *"Add to profile"*.

### Alternative Flows
- **Validation Error (e.g., Duplicate Skill):**
  - If candidate already has this skill under this category, form fails validation.
  - Server returns HTTP 422 with the re-rendered modal containing inline error messages: *"You already have this skill in your profile."*
  - The modal stays open, preventing loss of input.

---

## UC-06.3: Profile Record Creation & Targeted Single-Element Re-Evaluation

- **Primary Actor:** Candidate / Background AI Worker
- **Supporting System:** `jobs.tasks.match_job_element`, `jobs.tasks.enqueue_element_match`
- **Implemented by:** `jobs.services.profile_elements`, `jobs.services.add_to_profile`, `jobs.services.rematch_element`, `jobs.services.element_row_state`, `jobs.tasks.match_job_element`, `jobs.tasks.enqueue_element_match`, `jobs.domain.deepseek_client.match_single_element`, `jobs.domain.matcher.match_element_to_profile`
- **Objective:** Save the profile record and re-evaluate only the single affected job element in real-time.

### Main Success Scenario
1. Candidate submits valid form via AJAX POST to `/jobs/<pk>/elements/<elem_pk>/add/`.
2. Server executes `form.save()`:
   - Commits the new skill, language, experience highlight, degree, or benefit to `request.profile`.
3. Server records timestamp: `element.added_to_profile_at = timezone.now()`.
4. Server starts asynchronous re-evaluation via `enqueue_element_match(element)`:
   - Sets `element.is_evaluating = True`.
   - Creates an `AITask` (`kind="job_match"`).
   - Dispatches Celery task `match_job_element.s(element.pk, task.pk)`.
5. Server returns JSON response containing `task_id`, `element_id`, and initial spinner row HTML.
6. Browser closes modal and swaps the element row in the table to display a live loading indicator.
7. Background Celery Worker executes `match_job_element`:
   - Builds fresh profile slice for that section.
   - Submits single-element prompt to DeepSeek AI.
   - DeepSeek re-evaluates the requirement against the updated profile data.
   - Updates `element.match_level` (e.g. from `none` to `strong`) and writes updated `evidence`.
   - Clears `element.is_evaluating = False`.
   - Marks `AITask` as `done`.
8. Front-end polls `/tasks/<task_id>/status/` until terminal, then fetches `/jobs/<pk>/elements/<elem_pk>/row/` ([`jobs:element_row`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L305-L322)).
9. Element row is dynamically swapped with updated match badge (*"Strong"*), positive evidence, and updated section match summary counters.

### Key Code References
- Handler: [`jobs.views.JobElementAddToProfileView.post`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L262-L290)
- Celery Task: [`jobs.tasks.match_job_element`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/tasks.py#L257-L293)
- Row Rendering Endpoint: [`jobs.views.JobElementRowView`](file:///home/sami/PycharmProjects/Github/easy-apply/jobs/views.py#L305)
