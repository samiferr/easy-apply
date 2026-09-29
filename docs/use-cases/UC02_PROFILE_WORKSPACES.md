# Use Case Group 02: Workspaces & Multi-Profile Management

## System Scope
In Easy Apply, candidate data is isolated by **Workspace Profiles** (`accounts.Profile`). A user can maintain multiple profiles (e.g. for different industries, seniority levels, or languages). Every profile possesses a strict, immutable language contract.

---

## UC-02.1: Workspace / Profile Creation with Immutable Language Contract

- **Primary Actor:** Candidate
- **Supporting System:** `staffportal.domain.quotas`
- **Implemented by:** `accounts.services.profiles_of`, `accounts.services.default_profile_name`, `accounts.services.bootstrap_profile`, `accounts.services.set_active_profile`, `accounts.services.create_profile`
- **Objective:** Create a new isolated workspace with a specific name and language setting.

### Preconditions
1. User is authenticated.
2. User has not exceeded the `max_profiles` limit specified by their active subscription plan (verified via `quotas.profile_blocked_message`).

### Main Success Scenario
1. Candidate navigates to `/profiles/create/` ([`accounts:profile_create`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. System displays the profile creation form with fields:
   - **Name:** (e.g., *"Backend Engineer"*, *"Consultant Senior"*)
   - **Language:** Dropdown of supported languages (e.g., English `en`, French `fr`).
3. System explicitly displays a warning badge indicating that the profile language **cannot be altered after creation**.
4. Candidate enters the profile name and selects the target language.
5. Candidate submits the form (POST).
6. System checks `quotas.profile_blocked_message(request.user)`:
   - If user is under plan allowance, proceed.
7. System saves the new `accounts.Profile` instance linked to `request.user`.
8. System automatically switches the active workspace to this newly created profile:
   - Sets `request.session["active_profile_id"] = profile.id`
   - Sets cookie `active_profile_id`
   - Activates `django.utils.translation.activate(profile.language)`
9. Candidate is redirected to the Profile Overview page ([`accounts:profile`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)) with a confirmation message.

### Alternative / Exceptional Flows
- **Plan Profile Limit Reached:**
  - If the user's plan limits profiles (e.g. 1 profile on Free plan) and quota is reached:
  - Form validation fails with message: *"Your plan allows X profile(s). Delete one, or upgrade, to add another."*
  - Creation is blocked.

### Postconditions
- A new `accounts.Profile` row is created with completion percentage initialized to 0%.
- The new profile becomes the active context for all subsequent domain queries.

### Key Code References
- View: [`accounts.views.ProfileCreateView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L254-L288)
- Model: [`accounts.models.Profile`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/models.py#L55)
- Quota Service: [`staffportal.domain.quotas.profile_limit`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/quotas.py#L76-L84)

---

## UC-02.2: Active Workspace Switching & Locale Activation

- **Primary Actor:** Candidate
- **Supporting System:** `core.middleware.ActiveProfileMiddleware`, `django.utils.translation`
- **Implemented by:** `accounts.services.profiles_of`, `accounts.services.get_active_profile`, `accounts.services.set_active_profile`, `accounts.services.switch_profile`, `accounts.services.follow_profile_language`
- **Objective:** Seamlessly switch context between profiles and synchronize the user interface and AI language context.

### Preconditions
1. User possesses at least two profiles.

### Main Success Scenario
1. From the top navigation bar or workspace dropdown, the candidate clicks on a different profile.
2. An HTTP POST request is submitted to `/profiles/<pk>/switch/` ([`accounts:profile_switch`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
3. System validates that the requested profile ID belongs to `request.user`.
4. System updates `request.session["active_profile_id"] = profile.pk`.
5. System sets a persistent response cookie `active_profile_id`.
6. System activates the profile's declared language via `django.utils.translation.activate(profile.language)` and updates the Django language cookie `django_language`.
7. System redirects user back to the referring page (or dashboard).
8. All subsequent page views now resolve `request.profile` to the selected profile.

### Alternative Flows
- **Attempting to Switch to Another User's Profile:**
  - View performs `get_object_or_404(Profile, pk=pk, user=request.user)`. If ID belongs to another user, an HTTP 404 is returned.

### Key Code References
- View: [`accounts.views.ProfileSwitchView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L290-L310)
- Middleware: [`core.middleware.ActiveProfileMiddleware`](file:///home/sami/PycharmProjects/Github/easy-apply/core/middleware.py)

---

## UC-02.3: Profile Metadata & Contact Information Updates

- **Primary Actor:** Candidate
- **Supporting System:** Completion Percentage Calculation (`Profile.update_completion_percent()`)
- **Implemented by:** `accounts.services.update_personal_info`
- **Objective:** Edit candidate contact info, biography, headline, portfolio links, and avatar image.

### Main Success Scenario
1. Candidate navigates to `/profile/` ([`accounts:profile`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. Candidate fills in or updates metadata:
   - **Headline** (e.g. *"Staff Python Architect | AI Engineer"*)
   - **Bio / Summary**
   - **Phone Number**, **Location**
   - **External Links:** LinkedIn, Portfolio, GitHub
   - **Avatar Image** (optional file upload)
3. Candidate submits the form (POST).
4. System validates inputs (URLs, file extensions for avatar).
5. System persists changes to `request.profile`.
6. System invokes `profile.update_completion_percent()`:
   - Evaluates presence of contact fields, bio, headline, skills, work experience, education, and job preferences.
   - Calculates weighted completion percentage (0% to 100%).
7. System renders updated profile with success banner.

### Key Code References
- View: [`accounts.views.ProfileDetailView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L201-L235)
- Form: [`accounts.forms.ProfileForm`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/forms.py)
- Model Method: [`accounts.models.Profile.update_completion_percent`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/models.py#L110-L160)

---

## UC-02.4: Workspace Renaming & Deletion Guards

- **Primary Actor:** Candidate
- **Implemented by:** `accounts.services.profiles_of`, `accounts.services.rename_profile`, `accounts.services.ensure_profile_deletable`, `accounts.services.delete_profile`
- **Objective:** Rename an existing profile or delete a redundant profile while enforcing data integrity rules.

### Main Success Scenario (Renaming)
1. Candidate navigates to `/profiles/<pk>/rename/` ([`accounts:profile_rename`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. Candidate inputs a new workspace name.
3. System updates `Profile.name` and saves.

### Main Success Scenario (Deletion)
1. Candidate navigates to `/profiles/<pk>/delete/` ([`accounts:profile_delete`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. System checks total profile count for this user:
   - If count is 1: deletion is rejected with warning: *"You cannot delete your only profile."*
3. If count > 1: system displays confirmation dialog warning that all records belonging to this profile will be purged.
4. Candidate confirms deletion.
5. System deletes `profile`:
   - Cascades deletion to its skills, languages, experiences, education, preferences, job posts, resume imports, and tailored resumes.
6. System binds another remaining profile to `request.session["active_profile_id"]`.
7. Candidate is redirected to profile list.

### Key Code References
- Views: [`accounts.views.ProfileRenameView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L312-L330), [`accounts.views.ProfileDeleteView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L332-L370)

---

## UC-02.5: Full Profile Recap Export & Markdown Preview

- **Primary Actor:** Candidate
- **Supporting System:** `core.services.generate_markdown_recap`, `core.language.use_language`
- **Implemented by:** `core.services.generate_markdown_recap`, `core.services.recap_filename`
- **Objective:** Generate and download a comprehensive, professional Markdown summary of the entire active profile.

### Main Success Scenario
1. Candidate clicks *"Export Markdown Recap"* from profile settings or dashboard.
2. Candidate can preview the document at `/export/preview/` ([`core:export_preview`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py)).
3. Candidate clicks download, sending GET to `/export/markdown/` ([`core:export_markdown`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py)).
4. System executes `core.services.generate_markdown_recap(request.profile)`:
   - Wraps execution inside `use_language(profile.language)`.
   - Formats contact details, bio, soft skills, technical skills by category with level displays.
   - Formats languages with proficiencies.
   - Formats work experience with translated duration labels (e.g. *"Jan 2020 – Present"* or *"janv. 2020 – Aujourd'hui"*).
   - Formats education degrees and certificates with dates and URLs.
5. System returns an `HttpResponse` with `content_type="text/markdown; charset=utf-8"` and attachment header filename (e.g., `sami-backend-engineer-easy-apply-recap.md`).

### Key Code References
- Views: [`core.views.ExportMarkdownView`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py#L102-L115), [`core.views.ExportPreviewView`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py#L118-L126)
- Logic: [`core.services.generate_markdown_recap`](file:///home/sami/PycharmProjects/Github/easy-apply/core/services.py#L24-L135)
