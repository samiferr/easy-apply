# Use cases

Every documented use case is implemented by functions the code names back: a
`# UC-xx.y — Title (step n)` comment sits directly above each public function in an
app's `services.py` (and above the Celery tasks and building blocks a service
starts). Each use case below carries an **Implemented by** line listing them.

`core.tests.ServiceTraceabilityTests` keeps the code side honest: every app has a
`services.py` that names its use-case document, every public service cites a
`UC-xx.y` that is documented here, and each of UC01–UC09 is implemented by at
least one service. When you add a use case, document it here first, then cite it.

| Document | Use cases | Services | Lower layers it also cites |
| --- | --- | --- | --- |
| [UC01 — Identity, Authentication & Account Security](UC01_IDENTITY_AUTH_SECURITY.md) | 6 | `accounts/services.py`, `core/services.py`, `staffportal/services.py` | — |
| [UC02 — Workspaces & Multi-Profile Management](UC02_PROFILE_WORKSPACES.md) | 5 | `accounts/services.py`, `core/services.py` | — |
| [UC03 — Candidate Profile Data Management](UC03_PROFILE_DATA_MANAGEMENT.md) | 6 | `education/services.py`, `experience/services.py`, `languages/services.py`, `preferences/services.py`, `skills/services.py` | — |
| [UC04 — Resume Parsing & Automated Profile Onboarding](UC04_RESUME_PARSING_ONBOARDING.md) | 4 | `resume/services.py` | `resume/domain/deepseek_resume.py`, `resume/domain/extractor.py`, `resume/domain/importer.py`, `resume/tasks.py` |
| [UC05 — Job Posting Ingestion & Scoped Semantic Matching](UC05_JOB_POSTING_MATCHING.md) | 7 | `core/services.py`, `jobs/services.py` | `jobs/domain/deepseek_client.py`, `jobs/domain/importer.py`, `jobs/domain/matcher.py`, `jobs/tasks.py` |
| [UC06 — Interactive Requirement Gap-Closing ("Add to Profile")](UC06_INTERACTIVE_ADD_TO_PROFILE.md) | 3 | `jobs/services.py` | `jobs/domain/deepseek_client.py`, `jobs/domain/matcher.py`, `jobs/tasks.py` |
| [UC07 — Tailored Resume Authoring & PDF Export](UC07_TAILORED_RESUME_GENERATION.md) | 4 | `core/services.py`, `resume/services.py` | `resume/domain/pdf.py`, `resume/domain/tailored.py`, `resume/tasks.py` |
| [UC08 — Staff Operator Portal & SaaS Administration](UC08_STAFF_OPERATIONS_ADMIN.md) | 11 | `staffportal/services.py` | — |
| [UC09 — Legal Compliance, Localization & Cross-Cutting Architecture](UC09_COMPLIANCE_LOCALIZATION.md) | 4 | `core/services.py`, `legal/services.py` | `core/language.py` |

UC-01.3 (password reset by token) and UC-01.5 (sign-out) are Django's own views,
wired in `accounts/urls.py`; there is no service function for them to cite.

The layers a use case passes through are described in the top-level
[README](../../README.md#how-the-code-is-organised).
