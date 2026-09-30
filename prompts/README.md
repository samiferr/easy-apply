# AI prompts

Every prompt Easy Apply sends to the model lives in this directory, one prompt
per file. Nothing in the Python code contains prompt text: the code builds the
*data* a prompt talks about (the job posting, a profile slice, the resume text)
and `core/prompts.py::load_prompt` supplies the *instructions*.

```
prompts/
  core/    language_clause.txt          instruction prepended to every AI call
  jobs/    extract_sections.txt         job posting  -> the 13 fixed sections
           match_section.txt            one section  -> a verdict per row
  resume/  parse/<section>.txt          resume text  -> one section of the profile
           parse/shared.txt             role and rules common to every parse section
           skill_categories_note.txt    hint appended to the resume-parse call
           write/<section>.txt          job + profile -> one section of the resume
           write/shared.txt             role and rules common to every resume section
```

## The prompts

| File | Sent as | Used by | Variables |
| --- | --- | --- | --- |
| `core/language_clause.txt` | start of the **user** message, every call | `core.language.language_clause` | `language` |
| `jobs/extract_sections.txt` | **system** | `jobs.domain.deepseek_client.analyze_job_text` (UC-05.2) | `section_spec` |
| `jobs/match_section.txt` | **system** | `match_section` and `match_single_element` (UC-05.3, UC-06.3) | — |
| `resume/parse/shared.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — role and rules common to every section | — |
| `resume/parse/profile.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — contact details, headline, bio | — |
| `resume/parse/skills.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — soft and technical skills | — |
| `resume/parse/languages.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — spoken languages | — |
| `resume/parse/experience.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — work experience | — |
| `resume/parse/degrees.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — degrees | — |
| `resume/parse/certificates.txt` | **system** (shared + section, one call per section, in parallel) | `analyze_resume_text` (UC-04.2) — certificates | — |
| `resume/skill_categories_note.txt` | **user** message, after the language clause | `analyze_resume_text` (UC-04.2) | `soft_categories`, `technical_categories` |
| `resume/write/shared.txt` | **system** (shared + section, one call per section, in parallel) | `generate_tailored_resume` (UC-07.1) — role and rules common to every section | — |
| `resume/write/summary.txt` | **system** (shared + section, one call per section, in parallel) | `generate_tailored_resume` (UC-07.1) — professional summary | — |
| `resume/write/skills.txt` | **system** (shared + section, one call per section, in parallel) | `generate_tailored_resume` (UC-07.1) — skills | — |
| `resume/write/experience.txt` | **system** (shared + section, one call per section, in parallel) | `generate_tailored_resume` (UC-07.1) — work experience | — |
| `resume/write/education.txt` | **system** (shared + section, one call per section, in parallel) | `generate_tailored_resume` (UC-07.1) — education and certificates | — |
| `resume/write/languages.txt` | **system** (shared + section, one call per section, in parallel) | `generate_tailored_resume` (UC-07.1) — languages | — |

## Why plain `.txt` and not `.md`

These files are sent to the model **exactly as written**. Markdown invites
tools to help: editors and formatters re-wrap lines and renumber lists, and
GitHub's preview folds single newlines into spaces and swallows something like
`<one of the keys above>` as an HTML tag — so what you review is no longer what
the model reads. A `.txt` file is shown, diffed and shipped raw.
(`templates/resume_template.md` is different on purpose: it is a Markdown
*document* that the resume writer fills in, not an instruction.)

## Conventions

* **What you see is what the model gets.** A paragraph is one long line and a
  blank line separates paragraphs, exactly as the model receives them. Please
  don't re-wrap. The single newline at the end of a file is part of the prompt
  for the system prompts, and is stripped for the two user-message fragments.
* **Placeholders are `{{ name }}`** and nothing else is interpreted, so JSON
  braces, quotes, `$` and backslashes are written as they should be seen.
  `load_prompt` refuses to run when a placeholder has no value *or* a value has
  no placeholder, so a typo cannot silently reach the model. There is
  deliberately no way to write a literal `{{ name }}`.
* **UTF-8**, LF line endings.
* **A prompt is half of a contract.** Each prompt that asks for JSON names the
  keys the parsing code reads (`jobs/domain/importer.py`,
  `jobs/domain/matcher.py`, `resume/services.py`,
  `resume/domain/tailored.py`). If you rename a key here, rename it there —
  the `*PromptContractTests` classes in `jobs/tests.py` and `resume/tests.py` fail when
  the two drift apart.

## Editing a prompt

Change the file. The development server restarts on its own (`core/apps.py`
watches this directory); a Celery worker, like for any code change, has to be
restarted. Prompts are read once, when the module that owns them is imported, so
a missing file stops the app at start-up rather than at the first AI call.

## Adding a prompt

1. Create `prompts/<app>/<name>.txt`.
2. Load it with `core.prompts.load_prompt("<app>/<name>", **variables)` in the
   module that owns it — at import time for a fixed system prompt.
3. Add it to the table above, and a contract test if code parses its output.
