# Use Case Group 01: Identity, Authentication & Account Security

## System Scope
The `accounts` app handles identity verification, credential security, session management, and GDPR-compliant account erasure. Authentication is email-driven (no traditional usernames).

---

## UC-01.1: User Registration & Auto-Subscription

- **Primary Actor:** Anonymous Visitor
- **Supporting System:** `staffportal.domain.runtime_settings`, `staffportal.domain.subscriptions`, `accounts.models.Profile`
- **Implemented by:** `accounts.services.signups_open`, `accounts.services.complete_registration`, `accounts.services.default_profile_name`, `accounts.services.bootstrap_profile`, `core.services.build_dashboard`, `core.services.jobs_per_day_chart`, `staffportal.services.provision_subscription`
- **Objective:** Establish a new customer account, instantiate their primary workspace profile, and enroll them into the SaaS default subscription plan.

### Preconditions
1. The visitor is not authenticated.
2. The runtime setting `signups_enabled` is active (`True`).

### Main Success Scenario
1. Visitor navigates to `/register/` ([`accounts:register`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. System checks `runtime_settings.get("signups_enabled")`. Because signups are allowed, the registration form is rendered.
3. Visitor enters First Name, Last Name, Email, and Password (validated against Django's standard validators: length, similarity, numeric checks).
4. System validates inputs and creates an `accounts.User` record with `is_active=True`.
5. In an atomic transaction, the system:
   a. Creates a default `accounts.Profile` titled *"Default Profile"* in the system's active language context (`request.LANGUAGE_CODE`).
   b. Seeds the customer's subscription via [`subscriptions.ensure_subscription(user)`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/subscriptions.py), linking the account to the active default `staffportal.Plan`.
6. System logs the user into the session via Django auth backend.
7. System sets the `active_profile_id` session variable to the newly created profile ID.
8. System redirects the user to the onboarding dashboard ([`core:dashboard`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py)).

### Alternative / Exceptional Flows
- **Signups Disabled by Operator (Kill Switch):**
  - If `runtime_settings.get("signups_enabled")` is `False`, the registration endpoint returns a friendly error view stating that new registrations are temporarily closed.
- **Duplicate Email:**
  - If an account with the submitted email exists, the form displays a localized validation error: *"A user with that email already exists."*
- **Weak Password:**
  - Standard password validator warnings are shown; the form is not processed until requirements are satisfied.

### Postconditions
- A new `accounts.User` record is committed in SQLite.
- A linked `accounts.Profile` is created with completion percentage initialized to 0%.
- A linked `staffportal.Subscription` record is instantiated with status `active` (or `trialing` if plan includes trial days).
- User session is active.

### Key Code References
- View: [`accounts.views.RegisterView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L42-L73)
- Form: [`accounts.forms.RegistrationForm`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/forms.py)
- Models: [`accounts.models.User`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/models.py#L14), [`accounts.models.Profile`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/models.py#L55)
- Services: [`staffportal.domain.subscriptions.ensure_subscription`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/subscriptions.py)

---

## UC-01.2: Email Authentication & Session Inception

- **Primary Actor:** Anonymous Visitor / Candidate
- **Supporting System:** `django.contrib.auth`, `staffportal.middleware.LastSeenMiddleware`
- **Implemented by:** `accounts.services.apply_remember_me`, `accounts.services.get_active_profile`, `core.services.build_dashboard`
- **Objective:** Authenticate using email and password, bind the active profile workspace to the session, and access user data.

### Preconditions
1. User possesses an active registered account (`is_active=True`).

### Main Success Scenario
1. User visits `/login/` ([`accounts:login`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. User submits email and password.
3. System normalizes email to lowercase and authenticates credentials.
4. If valid, Django rotates session ID to prevent session fixation attacks.
5. System inspects user's profiles:
   a. If an existing `active_profile_id` in cookie/session is valid for this user, it is retained.
   b. Otherwise, the earliest created active profile is bound to `request.session['active_profile_id']`.
6. User's `last_seen_at` timestamp is updated by `LastSeenMiddleware`.
7. User is redirected to `next` URL or [`core:dashboard`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py).

### Alternative / Exceptional Flows
- **Invalid Credentials:**
  - Error message displayed: *"Please enter a correct email and password. Note that both fields may be case-sensitive."*
- **Account Suspended:**
  - If `user.is_active=False`, authentication fails; user cannot log in.
- **Maintenance Mode Active:**
  - If `runtime_settings.get("maintenance_mode")` is active and the user is not staff, requests are caught by middleware and directed to the maintenance view.

### Postconditions
- Authenticated session established in SQLite session store.
- Profile bound to session context.

### Key Code References
- View: [`accounts.views.EmailLoginView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L76-L95)
- Form: [`accounts.forms.EmailAuthenticationForm`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/forms.py)
- Middleware: [`core.middleware.ActiveProfileMiddleware`](file:///home/sami/PycharmProjects/Github/easy-apply/core/middleware.py), [`staffportal.middleware.LastSeenMiddleware`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/middleware.py)

---

## UC-01.3: Password Reset via Cryptographic Token

- **Primary Actor:** Anonymous Visitor / Candidate
- **Supporting System:** `django.contrib.auth.tokens.default_token_generator`, SMTP email backend
- **Objective:** Safely regain account access when credentials are forgotten without revealing password contents to anyone.

### Main Success Scenario
1. User clicks *"Forgot password?"* and navigates to `/password-reset/` ([`accounts:password_reset`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. User enters registered email address.
3. System checks database:
   a. If found and active, generates a cryptographically signed one-time token (`uidb64` + `token`).
   b. Dispatches a localized reset email containing the unique link to the user.
4. User receives the email and clicks the one-time link `/password-reset/<uidb64>/<token>/`.
5. System verifies token validity and timestamp expiry.
6. User inputs a new secure password twice.
7. System updates password hash using Argon2/PBKDF2 and renders success confirmation.
8. User proceeds to login with their new credentials.

### Alternative / Exceptional Flows
- **Unknown Email Entered:**
  - Generic success message displayed regardless to prevent email enumeration attacks.
- **Expired or Reused Token:**
  - System rejects with an error: *"The password reset link was invalid, possibly because it has already been used."*

### Key Code References
- URLs: [`accounts/urls.py`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py#L32-L55)
- Templates: `accounts/emails/password_reset_email.html`, `accounts/password_reset_form.html`

---

## UC-01.4: Credential Modification (Password Change)

- **Primary Actor:** Candidate (Logged in)
- **Implemented by:** `accounts.services.change_password`
- **Objective:** Update current account password from within account security settings.

### Main Success Scenario
1. User navigates to `/security/` ([`accounts:security`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. User submits old password and validates the new password twice.
3. System verifies old password match, validates new password complexity, and commits the updated hash.
4. System executes `update_session_auth_hash(request, user)` so the user remains logged in without session termination.
5. System displays success banner: *"Your password has been changed successfully."*

### Alternative / Exceptional Flows
- **Old Password Incorrect:** Form re-rendered with validation error.
- **Impersonated Session Guard:** Staff members impersonating a user cannot change customer credentials.

### Key Code References
- View: [`accounts.views.SecurityView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L98-L130)
- Form: `django.contrib.auth.forms.PasswordChangeForm`

---

## UC-01.5: Secure User Logout & Session Invalidation

- **Primary Actor:** Candidate
- **Objective:** Conclude user session and clean up local auth state.

### Main Success Scenario
1. User clicks *"Sign out"* in navigation bar.
2. System presents confirmation dialog/screen ([`accounts:logout`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
3. Upon POST confirmation, `django.contrib.auth.logout(request)` is executed:
   a. Flushes session record from server database.
   b. Clears session cookies.
4. User redirected to public home page ([`core:home`](file:///home/sami/PycharmProjects/Github/easy-apply/core/views.py)).

### Key Code References
- View: [`accounts.views.logout_confirm_view`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L133-L148)

---

## UC-01.6: Self-Service Account Erasure (GDPR Art. 17)

- **Primary Actor:** Candidate (Logged in)
- **Supporting System:** Django cascading deletes, `accounts.models.User.delete()`
- **Implemented by:** `accounts.services.delete_account`
- **Objective:** Exercise "Right to be Forgotten" by permanently deleting the user account and all personal career data.

### Preconditions
1. User is authenticated.
2. Session is NOT an impersonated session.

### Main Success Scenario
1. User navigates to `/delete-account/` ([`accounts:delete_account`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/urls.py)).
2. System displays a warning modal stating that erasure is permanent and will delete all profiles, skills, experiences, uploaded resumes, job analyses, and tailored documents.
3. User is required to type their exact email address to confirm identity and consent.
4. Upon POST submission, system verifies email string equality.
5. System calls `user.delete()`:
   a. SQLite cascading deletion removes all linked `Profile` objects.
   b. Cascade removes `UserSkill`, `UserLanguage`, `WorkExperience`, `ExperienceHighlight`, `Degree`, `Certificate`, `JobPreference`, `BenefitPreference`, `JobPost`, `JobSection`, `JobElement`, `ResumeImport`, and `TailoredResume`.
   c. Associated uploaded files on disk are unlinked.
   d. User's `Subscription` and `UsageRecord` rows are removed.
   e. Note: Any prior staff `AuditLog` rows referencing this user set their `actor` or `target` to `NULL` but retain the denormalized `actor_email` and `target_repr` for regulatory accountability.
6. Session is terminated and user is redirected to landing page with message: *"Your account and all associated data have been permanently deleted."*

### Alternative Flows
- **Mismatched Email Confirmation:** Form error displayed; deletion is aborted.
- **Impersonator Block:** Staff members impersonating a user are denied execution of this view.

### Key Code References
- View: [`accounts.views.AccountDeleteView`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/views.py#L151-L195)
- Model Cascade: [`accounts.models.User`](file:///home/sami/PycharmProjects/Github/easy-apply/accounts/models.py#L14)
