# Use Case Group 03: Candidate Profile Data Management

## System Scope
The candidate profile data model is decomposed into specialized apps:
- `skills`: Technical and soft skills categorized into tabs, with level metrics.
- `languages`: Multilingual competencies and proficiency standards.
- `experience`: Chronological work history and granular highlight bullet points.
- `education`: Academic degrees and industry certifications.
- `preferences`: Target compensation, work arrangements, location constraints, and prioritized fringe benefits.

---

## UC-03.1: Technical Skills Management by Category Tabs

- **Primary Actor:** Candidate
- **Supporting System:** `skills.models.SkillCategory`, `skills.models.UserSkill`
- **Implemented by:** `skills.services.is_valid_kind`, `skills.services.profile_skills`, `skills.services.skills_by_category`, `skills.services.group_by_category`, `skills.services.add_skill`, `skills.services.update_skill`, `skills.services.remove_skill`
- **Objective:** Record, update, and categorize technical competencies (e.g. Languages, Frameworks, Databases, Cloud) with proficiency ratings.

### Main Success Scenario
1. Candidate navigates to `/skills/technical/` ([`skills:list` with kind="technical"](file:///home/sami/PycharmProjects/Github/easy-apply/skills/views.py#L42-L65)).
2. System groups candidate's technical skills by category tab (`_grouped_by_category`).
3. Candidate clicks *"Add a technical skill"*, opening `/skills/technical/add/` ([`skills:create`](file:///home/sami/PycharmProjects/Github/easy-apply/skills/views.py#L79-L88)).
4. Candidate selects or inputs:
   - **Category:** (Filtered to `kind="technical"`, e.g. "Languages & Runtimes", "Databases & Storage")
   - **Skill Name:** (e.g., *"PostgreSQL"*, *"Python"*)
   - **Proficiency Level:** Beginner (1), Intermediate (2), Advanced (3), Expert (4).
5. Candidate submits the form (POST).
6. System verifies uniqueness constraint `unique_skill_per_profile_category`:
   - Enforces that the same skill name is not duplicated within the same category for this profile.
7. System saves `UserSkill` tied to `request.profile`.
8. System redirects user back to `/skills/technical/#category-<id>` with success toast.

### Alternative Flows
- **Duplicate Skill Submission:**
  - Database constraint or form validation surfaces an inline error: *"You have already recorded this skill under this category."*
- **Skill Editing / Deletion:**
  - Candidate can edit proficiency or rename at `/skills/technical/<pk>/edit/`.
  - Candidate can delete at `/skills/technical/<pk>/delete/` with confirmation modal ([`ConfirmDeleteMixin`](file:///home/sami/PycharmProjects/Github/easy-apply/core/mixins.py)).

### Key Code References
- Views: [`skills.views.SkillListView`](file:///home/sami/PycharmProjects/Github/easy-apply/skills/views.py#L54), [`skills.views.SkillCreateView`](file:///home/sami/PycharmProjects/Github/easy-apply/skills/views.py#L79), [`skills.views.SkillDeleteView`](file:///home/sami/PycharmProjects/Github/easy-apply/skills/views.py#L96)
- Models: [`skills.models.SkillCategory`](file:///home/sami/PycharmProjects/Github/easy-apply/skills/models.py#L4), [`skills.models.UserSkill`](file:///home/sami/PycharmProjects/Github/easy-apply/skills/models.py#L25)

---

## UC-03.2: Soft Skills Management & Categorization

- **Primary Actor:** Candidate
- **Supporting System:** `skills.models.SkillCategory (kind="soft")`
- **Implemented by:** `skills.services.is_valid_kind`, `skills.services.profile_skills`, `skills.services.skills_by_category`, `skills.services.add_skill`
- **Objective:** Curate interpersonal, leadership, and operational soft skills.

### Main Success Scenario
1. Candidate navigates to `/skills/soft/` ([`skills:list` with kind="soft"](file:///home/sami/PycharmProjects/Github/easy-apply/skills/views.py#L54)).
2. Candidate clicks *"Add a soft skill"*.
3. Candidate selects category (e.g., "Leadership & People", "Communication & Collaboration"), enters skill name (e.g. *"Cross-functional Mentorship"*), and assigns proficiency level (1–4).
4. System validates and saves record to `request.profile`.
5. System returns user to the corresponding category anchor with a confirmation message.

---

## UC-03.3: Multilingual Language Proficiencies Management

- **Primary Actor:** Candidate
- **Supporting System:** `languages.models.Language`, `languages.models.UserLanguage`
- **Implemented by:** `languages.services.profile_languages`, `languages.services.list_languages`, `languages.services.add_language`, `languages.services.update_language`, `languages.services.remove_language`
- **Objective:** Declare spoken and written language capabilities.

### Main Success Scenario
1. Candidate navigates to `/languages/` ([`languages:list`](file:///home/sami/PycharmProjects/Github/easy-apply/languages/views.py#L12-L18)).
2. System lists recorded languages ordered alphabetically.
3. Candidate clicks *"Add a language"*, opening form at `/languages/add/`.
4. Candidate enters:
   - **Language Name:** (Auto-complete / case-insensitive lookup against shared `languages.Language` table, creating it if new).
   - **Proficiency:** Basic, Conversational, Professional working proficiency, Fluent, Native / bilingual.
5. System checks constraint `unique_language_per_profile`.
6. System persists `UserLanguage` linked to `request.profile`.
7. User is redirected to `/languages/` displaying percentage bar corresponding to proficiency.

### Key Code References
- Views: [`languages.views.LanguageListView`](file:///home/sami/PycharmProjects/Github/easy-apply/languages/views.py#L12), [`languages.views.LanguageCreateView`](file:///home/sami/PycharmProjects/Github/easy-apply/languages/views.py#L31)
- Models: [`languages.models.Language`](file:///home/sami/PycharmProjects/Github/easy-apply/languages/models.py#L5), [`languages.models.UserLanguage`](file:///home/sami/PycharmProjects/Github/easy-apply/languages/models.py#L14)

---

## UC-03.4: Professional Work Experience & Granular Highlights

- **Primary Actor:** Candidate
- **Supporting System:** `experience.models.WorkExperience`, `experience.models.ExperienceHighlight`, Django FormSets
- **Implemented by:** `experience.services.profile_experiences`, `experience.services.list_experiences`, `experience.services.save_experience`, `experience.services.remove_experience`
- **Objective:** Record comprehensive employment history with discrete, re-orderable achievement bullet points.

### Main Success Scenario
1. Candidate navigates to `/experience/` ([`experience:list`](file:///home/sami/PycharmProjects/Github/easy-apply/experience/views.py#L15-L23)).
2. Candidate clicks *"Add work experience"* ([`experience:create`](file:///home/sami/PycharmProjects/Github/easy-apply/experience/views.py#L64-L67)).
3. Form renders parent `WorkExperience` fields and inline `HighlightFormSet`:
   - **Job Title:** (e.g., *"Lead Backend Developer"*)
   - **Company Name:** (e.g., *"TechCorp Ltd"*)
   - **Location:** (e.g., *"Paris, France"*)
   - **Employment Type:** Full-time, Part-time, Contract, Freelance, Internship.
   - **Dates:** Start Date, End Date, and *"I currently work here"* checkbox.
   - **Highlights:** Dynamic list of individual achievement bullet points (up to 500 characters each), with order sorting.
4. Candidate fills in experience details and adds multiple distinct highlight items.
5. If *"I currently work here"* is checked, `end_date` is automatically cleared by model validation (`clean()`).
6. Candidate submits the form.
7. System validates in a database transaction:
   - Verifies `start_date <= end_date` (if not current).
   - Saves parent `WorkExperience` linked to `request.profile`.
   - Saves all highlight rows with appropriate ordering values.
8. Candidate is redirected to `/experience/` displaying formatted duration label (e.g., *"Jan 2021 – Present"*).

### Key Code References
- Views: [`experience.views.BaseExperienceFormView`](file:///home/sami/PycharmProjects/Github/easy-apply/experience/views.py#L26-L61)
- Models: [`experience.models.WorkExperience`](file:///home/sami/PycharmProjects/Github/easy-apply/experience/models.py#L7), [`experience.models.ExperienceHighlight`](file:///home/sami/PycharmProjects/Github/easy-apply/experience/models.py#L50)

---

## UC-03.5: Education Degrees & Professional Certifications

- **Primary Actor:** Candidate
- **Supporting System:** `education.models.Degree`, `education.models.Certificate`
- **Implemented by:** `education.services.profile_degrees`, `education.services.profile_certificates`, `education.services.education_overview`, `education.services.add_degree`, `education.services.update_degree`, `education.services.remove_degree`, `education.services.add_certificate`, `education.services.update_certificate`, `education.services.remove_certificate`
- **Objective:** Track academic background and verified credentials.

### Main Success Scenario (Degree)
1. Candidate navigates to `/education/` ([`education:list`](file:///home/sami/PycharmProjects/Github/easy-apply/education/views.py#L12-L21)).
2. Candidate clicks *"Add degree"*, specifying School, Degree level (Bachelor's, Master's, PhD), Field of Study, Dates, and optional Grade/Description.
3. System saves `Degree` record to `request.profile`.

### Main Success Scenario (Certification)
1. Candidate clicks *"Add certificate"*, specifying Name, Issuing Organization, Issue Date, Expiry Date (or *"Does not expire"*), Credential ID, and Credential URL.
2. System saves `Certificate` record to `request.profile`. System dynamically exposes the `is_expired` property on dashboard views.

### Key Code References
- Views: [`education.views.EducationListView`](file:///home/sami/PycharmProjects/Github/easy-apply/education/views.py#L12), [`education.views.DegreeCreateView`](file:///home/sami/PycharmProjects/Github/easy-apply/education/views.py#L32), [`education.views.CertificateCreateView`](file:///home/sami/PycharmProjects/Github/easy-apply/education/views.py#L65)
- Models: [`education.models.Degree`](file:///home/sami/PycharmProjects/Github/easy-apply/education/models.py#L5), [`education.models.Certificate`](file:///home/sami/PycharmProjects/Github/easy-apply/education/models.py#L24)

---

## UC-03.6: Career Preferences, Work Arrangements & Benefits Prioritization

- **Primary Actor:** Candidate
- **Supporting System:** `preferences.models.JobPreference`, `preferences.models.BenefitPreference`
- **Implemented by:** `preferences.services.get_or_create_preference`, `preferences.services.preference_screen`, `preferences.services.save_preferences`, `preferences.services.profile_benefits`, `preferences.services.add_benefit`, `preferences.services.change_benefit_importance`, `preferences.services.remove_benefit`
- **Objective:** Define explicit compensation requirements, geographical/remote flexibility, and prioritized fringe benefits used for semantic matching against job listings.

### Main Success Scenario
1. Candidate navigates to `/preferences/` ([`preferences:detail`](file:///home/sami/PycharmProjects/Github/easy-apply/preferences/views.py#L13-L36)).
2. If opening for the first time, `get_or_create_preference(profile)` auto-seeds 12 standard benefits (`SEED_BENEFITS`: Health benefits, Dental care, Vision, 401k/Pension, PTO, Parental leave, Equity, Remote stipend, etc.) set to `nice_to_have`.
3. Candidate updates scalar preferences:
   - **Compensation:** Min Salary, Max/Target Salary, Currency (EUR, USD, GBP, etc.), Period (year, month, day, hour).
   - **Location:** Line-separated preferred cities/countries, open to Remote / Hybrid / On-site flags, max on-site days/week, willing to relocate flag, max travel percentage, timezone preference.
4. Candidate modifies benefit priorities in the table:
   - Changes importance dropdown inline to: `must_have`, `nice_to_have`, or `not_important`.
   - Adds custom benefits (e.g. *"Company Car"*, *"Tuition Reimbursement"*).
5. Candidate clicks save; system updates `JobPreference` and `BenefitPreference` rows.

### Key Code References
- Views: [`preferences.views.JobPreferenceView`](file:///home/sami/PycharmProjects/Github/easy-apply/preferences/views.py#L13), [`preferences.views.BenefitUpdateView`](file:///home/sami/PycharmProjects/Github/easy-apply/preferences/views.py#L52-L65)
- Models: [`preferences.models.JobPreference`](file:///home/sami/PycharmProjects/Github/easy-apply/preferences/models.py#L5), [`preferences.models.BenefitPreference`](file:///home/sami/PycharmProjects/Github/easy-apply/preferences/models.py#L93)
