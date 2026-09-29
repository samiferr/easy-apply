# Use Case Group 08: Staff Operator Portal & SaaS Administration

## System Scope
The `staffportal` app provides operators, support agents, billing managers, and system administrators with a unified console mounted at `/staff/`. It controls SaaS tenancy, role-based authorization, account diagnostics, audited impersonation, feature flagging, runtime settings, operational health, and regulatory compliance.

---

## UC-08.1: Granular Role-Based Access Control & Portal Obfuscation

- **Primary Actor:** Staff Member / Superuser
- **Supporting System:** `staffportal.domain.access`, `staffportal.views.base.StaffPortalMixin`
- **Objective:** Restrict operator functions using least privilege and hide portal existence from non-staff users.

### Security Rules & Capabilities Matrix
| Capability | Key | Viewer | Support | Billing | Admin | Superuser |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| Open Portal | `portal.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Read Accounts | `users.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Manage Accounts (Notes, Suspend) | `users.manage` | — | ✓ | ✓ | ✓ | ✓ |
| Impersonate Customers | `users.impersonate` | — | ✓ | ✓ | ✓ | ✓ |
| Export Personal Data (CSV/JSON) | `users.export` | — | ✓ | ✓ | ✓ | ✓ |
| Delete Accounts (GDPR Erasure) | `users.delete` | — | — | — | ✓ | ✓ |
| View Plans & Subscriptions | `billing.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Manage Plans & Subscriptions | `billing.manage` | — | — | ✓ | ✓ | ✓ |
| Feature Flags Management | `flags.manage` | — | — | — | ✓ | ✓ |
| Announcements Management | `announcements.manage` | — | — | — | ✓ | ✓ |
| Operational Health & Queue | `operations.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Queue Retry & Runtime Settings | `operations.manage` | — | — | — | ✓ | ✓ |
| View Audit Logs | `audit.view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| Manage Staff Team & Roles | `team.manage` | — | — | — | — | ✓ (Only) |

### Main Success Scenario
1. Authenticated user navigates to `/staff/`.
2. `StaffPortalMixin` inspects `request.user`:
   - If `is_staff=False` and `is_superuser=False`: returns **HTTP 404 Not Found** (not 403), completely concealing the portal's existence.
   - If user is in an active impersonation session: returns **HTTP 404** (an impersonated session cannot access staff tools).
3. If staff access is confirmed, system resolves their role via `access.role_for(user)`:
   - Evaluates whether the operator holds the required capability for the view.
   - If missing capability: returns HTTP 403 Permission Denied.
4. If authorized, renders the requested portal screen.

### Key Code References
- Capabilities & Roles: [`staffportal.domain.access`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/access.py)
- Mixin: [`staffportal.views.base.StaffPortalMixin`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/base.py)

---

## UC-08.2: Customer Account Administration, Filtering & Session-Flushing Suspension

- **Primary Actor:** Support Operator / Admin
- **Supporting System:** `staffportal.views.users.UserSuspendView`, `django.contrib.sessions`
- **Objective:** Locate customer accounts, view detailed status, and suspend abusive or compromised accounts with immediate session termination.

### Main Success Scenario
1. Operator navigates to `/staff/users/` ([`staffportal:user_list`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L16)).
2. Operator applies search query and filters (status: active/suspended/staff, plan tier, activity: recent/dormant).
3. Operator selects a specific account, opening `/staff/users/<pk>/` ([`staffportal:user_detail`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L18)):
   - Screen displays user details, profiles, active subscription, monthly usage allowances, recent job analyses, AI tasks, support notes, enabled feature flags, and audit history.
4. To suspend an account:
   - Operator submits reason via POST to `/staff/users/<pk>/suspend/` ([`staffportal:user_suspend`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L19)).
   - System updates `user.is_active = False`.
   - System executes `_flush_sessions(account)`: iterates through active Django session store, decodes payloads, and deletes all sessions matching `_auth_user_id == account.pk` to sever existing connections instantly.
   - System records append-only `AuditLog` entry.
   - Operator receives success notification.

### Key Code References
- Views: [`staffportal.views.users.UserListView`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/users.py#L65), [`staffportal.views.users.UserSuspendView`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/users.py#L156-L177)
- Session Flush: [`staffportal.views.users._flush_sessions`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/users.py#L365-L380)

---

## UC-08.3: Audited, Time-Limited Customer Impersonation

- **Primary Actor:** Support Operator / Superuser
- **Supporting System:** `staffportal.domain.impersonation`, `ImpersonationSession`
- **Objective:** Log in as a customer to diagnose issues safely, bounded by strict time limits and audit records.

### Safety Invariants
1. A reason is mandatory and recorded before the session opens.
2. The session automatically expires after `impersonation_minutes` (default 30 mins).
3. While impersonating, a persistent top banner is rendered on all pages.
4. The impersonated session **CANNOT access `/staff/*`**, cannot change customer credentials, and cannot self-delete the account.
5. Operators cannot impersonate themselves or deactivated users. Non-superusers cannot impersonate other staff accounts.

### Main Success Scenario
1. From user detail screen, operator enters an explicit reason and submits *"Sign in as this user"* (POST to `/staff/users/<pk>/impersonate/`).
2. System verifies `can_impersonate(actor, target)`.
3. System creates `ImpersonationSession` row with `expires_at = now + impersonation_minutes`.
4. System logs `AuditLog` with action `impersonation.started`.
5. System logs in the operator as the target customer using `impersonation.start(request, target, reason)`:
   - Preserves operator identity in `request.session["impersonator_id"]`.
6. Operator is redirected to candidate dashboard (`core:dashboard`). A prominent amber banner displays: *"Viewing as [customer email] — Session expires at [time] — Stop Impersonating"*.
7. Operator inspects user workspace, diagnosing the issue.
8. When finished, operator clicks *"Stop Impersonating"*:
   - POST to `/staff/impersonation/stop/` ([`staffportal:impersonate_stop`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L31)).
   - System closes `ImpersonationSession` row (`ended_reason="manual"`).
   - Logs `AuditLog` with action `impersonation.ended`.
   - Restores the original staff account session and redirects to `/staff/dashboard/`.

### Key Code References
- Service: [`staffportal.domain.impersonation`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/impersonation.py)
- Views: [`staffportal.views.users.ImpersonateStartView`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/users.py#L315), [`staffportal.views.users.ImpersonateStopView`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/users.py#L338)

---

## UC-08.4: Internal Customer Support Annotations

- **Primary Actor:** Support Operator
- **Supporting System:** `staffportal.models.SupportNote`
- **Objective:** Attach internal notes, investigation details, and support tickets to customer accounts.

### Main Success Scenario
1. Operator views account detail screen `/staff/users/<pk>/`.
2. In the *"Support Notes"* card, operator enters note text and optionally toggles *"Pin to top"*.
3. Submits form (POST to `/staff/users/<pk>/notes/`).
4. System creates `SupportNote` linked to target user, author staff user, and email stamp.
5. System logs `AuditLog` entry `user.note_added`.
6. Note is displayed immediately in chronological / pinned order. Notes are strictly internal and never exposed to customers.

---

## UC-08.5: Plan Tier Definition & Subscription Management

- **Primary Actor:** Billing Operator / Admin
- **Supporting System:** `staffportal.models.Plan`, `staffportal.models.Subscription`, `staffportal.domain.quotas`
- **Objective:** Define SaaS pricing tiers, configure monthly feature quotas, and adjust customer plans.

### Main Success Scenario
1. Billing Operator navigates to `/staff/billing/` ([`staffportal:billing`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L34)).
2. Operator creates or edits a `Plan`:
   - Configures price (stored as integer cents, e.g. `2900` USD), billing interval (monthly/yearly), trial days.
   - Sets monthly allowances: `monthly_job_analyses`, `monthly_tailored_resumes`, `monthly_resume_imports`, and `max_profiles`. (`NULL` = unlimited; `0` = feature excluded).
3. On a customer detail page, Billing Operator can change plan tier or status (Active, Past Due, Canceled, Expired) via `/staff/users/<pk>/plan/`.
4. If an outage or AI failure consumed a customer's monthly allowance, operator clicks *"Reset Current Usage"* (`/staff/users/<pk>/usage/reset/`):
   - Zeroes the active period's `UsageRecord` count.
   - Writes audited record.

### Key Code References
- Views: [`staffportal.views.billing`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/billing.py)
- Models: [`staffportal.models.Plan`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/models.py#L70), [`staffportal.models.Subscription`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/models.py#L130), [`staffportal.models.UsageRecord`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/models.py#L190)

---

## UC-08.6: Dynamic Deterministic Feature Flags & Account Overrides

- **Primary Actor:** System Administrator
- **Supporting System:** `staffportal.models.FeatureFlag`, `staffportal.domain.flags`
- **Objective:** Toggle product features and release gradual rollouts without requiring code deployments.

### Main Success Scenario
1. Administrator navigates to `/staff/flags/` ([`staffportal:flag_list`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L48)).
2. Administrator creates or edits a flag:
   - State options:
     - `off`: Off for everyone.
     - `on`: Globally enabled.
     - `staff`: Enabled strictly for staff accounts.
     - `percent`: Percentage-based rollout (0% to 100%).
   - Overrides: Specific forced accounts (`users`) and specific plans (`plans`).
3. Evaluation via `flags.is_enabled(key, user)`:
   - Deterministic hashing: computes `md5(f"{user.pk}:{key}".encode()).hexdigest() % 100 < percentage`.
   - Guaranteed consistency: the same user always receives the exact same flag result across requests without cookie or session state.

### Key Code References
- Service: [`staffportal.domain.flags`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/flags.py)
- Views: [`staffportal.views.flags`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/flags.py)

---

## UC-08.7: Runtime Configuration & Emergency Service Kill Switches

- **Primary Actor:** System Administrator
- **Supporting System:** `staffportal.domain.runtime_settings`, Django cache
- **Objective:** Toggle emergency kill switches and operational settings with immediate cache invalidation.

### Registry of Runtime Settings
- `signups_enabled` (bool): Close public registrations during spam spikes or maintenance.
- `maintenance_mode` (bool): Locks out non-staff users, showing a polite maintenance banner.
- `ai_features_enabled` (bool): Emergency kill switch shutting off all outgoing DeepSeek AI API requests (prevents billing runaway or errors during upstream outages).
- `enforce_quotas` (bool): Enable or disable subscription quota enforcement.
- `impersonation_minutes` (int): Maximum lifespan of customer impersonation sessions.
- `audit_retention_days` (int): Days before old audit entries are pruned.
- `support_email` (str): Contact email rendered on user error and quota pages.

### Main Success Scenario
1. Administrator navigates to `/staff/operations/settings/` ([`staffportal:settings`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L71)).
2. Administrator toggles a switch (e.g., disables `ai_features_enabled`) and saves.
3. System calls `runtime_settings.set_value(key, value, user=request.user)`:
   - Saves to `SystemSetting` model.
   - Clears memory cache `staffportal:system-settings`.
   - Writes `AuditLog` entry.
4. All worker processes and web threads immediately respect the new setting.

### Key Code References
- Service: [`staffportal.domain.runtime_settings`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/domain/runtime_settings.py)
- View: [`staffportal.views.operations.SettingsView`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/views/operations.py)

---

## UC-08.8: Site-Wide Customer Announcements & In-App Banners

- **Primary Actor:** System Administrator
- **Supporting System:** `staffportal.models.Announcement`
- **Objective:** Display dismissible system announcements (maintenance notices, incident reports, product launches) across web sessions.

### Main Success Scenario
1. Administrator navigates to `/staff/announcements/new/` ([`staffportal:announcement_create`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L55)).
2. Administrator configures:
   - **Title & Body**
   - **Level:** `info`, `success`, `warning`, `critical`
   - **Audience:** `everyone`, `authenticated`, or `staff`
   - **Scheduling:** `starts_at` and optional `ends_at`
   - **Dismissible:** Boolean flag
3. Announcement appears instantly at the top of candidate web pages.
4. When a user dismisses the announcement, Alpine.js records the dismissal in local browser storage, suppressing it for that user.

---

## UC-08.9: Asynchronous Celery Queue Inspection & Task Re-dispatch

- **Primary Actor:** Support Operator / Admin
- **Supporting System:** `staffportal.views.operations`, `core.models.AITask`
- **Objective:** Monitor background AI jobs, detect failing tasks, view error traces, and manually re-dispatch failed tasks.

### Main Success Scenario
1. Operator navigates to `/staff/operations/queue/` ([`staffportal:task_list`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L65)).
2. System displays active, completed, and failed `AITask` records with task kind, user, percent completion, step name, error traces, and duration.
3. Operator selects a failed task and clicks *"Retry"* (`/staff/operations/queue/<pk>/retry/`):
   - System re-dispatches the appropriate Celery task signature.
   - Resets `state="queued"`, clears `error_message`.
4. Operator can also export queue metrics as CSV via `/staff/operations/queue/export.csv`.

---

## UC-08.10: Immutable Append-Only Audit Logging & Retention

- **Primary Actor:** Support / Billing / Admin / Superuser
- **Supporting System:** `staffportal.models.AuditLog`, `manage.py prune_audit_log`
- **Objective:** Maintain an unalterable forensic record of every action taken by staff accounts.

### Immutability Contract
- `AuditLog.save()` rejects modifications to existing entries (`ValueError("Audit log entries are immutable.")`).
- `AuditLog.delete()` prohibits individual row deletion (`ValueError("Audit log entries cannot be deleted individually.")`).
- Actor emails and target representations are denormalized so the trail remains coherent even if users are deleted.

### Main Success Scenario
1. Staff member executes any mutation in the portal (suspension, plan change, impersonation, setting change, note creation).
2. System invokes `staffportal.domain.audit.log(request, action, target, summary, ...)`:
   - Captures actor ID, `actor_email`, `ip_address` (handling proxy headers `X-Forwarded-For`), user agent, action key, target ID/repr, metadata JSON, and `while_impersonating` flag.
3. Records are viewable at `/staff/audit/` ([`staffportal:audit_list`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L73)) and exportable as CSV.
4. Old audit entries beyond `audit_retention_days` are safely trimmed in bulk via the scheduled management command `prune_audit_log`.

---

## UC-08.11: GDPR Art. 20 JSON Portability & Operator-Initiated Account Erasure

- **Primary Actor:** Support Operator / Admin
- **Supporting System:** `staffportal.domain.exports`, `staffportal.views.users.UserDeleteView`
- **Objective:** Deliver full data portability (GDPR Art. 20) and perform regulatory account erasure (GDPR Art. 17).

### Main Success Scenario (Data Portability Export)
1. Support Operator visits `/staff/users/<pk>/` and clicks *"Download Data Export (JSON)"* (`/staff/users/<pk>/export.json`).
2. System runs `staffportal.domain.exports.account_export_response(account)`:
   - Compiles user identity, profile details, skills, languages, work experiences with highlights, degrees, certificates, preferences, benefits, job posts with analyzed sections, tailored resumes, and usage records into a structured JSON file.
3. System writes `AuditLog` entry `user.exported`.
4. System streams JSON response.

### Main Success Scenario (Operator-Initiated Erasure)
1. Administrator navigates to `/staff/users/<pk>/delete/` ([`staffportal:user_delete`](file:///home/sami/PycharmProjects/Github/easy-apply/staffportal/urls.py#L23)).
2. Screen warns of irreversible destruction of candidate records.
3. Administrator must manually type the full email address of the account into the confirmation input.
4. System verifies email string match.
5. System logs `AuditLog` entry `user.deleted` containing target email and reason **before** deleting the record.
6. System calls `account.delete()`, executing full database cascade.
