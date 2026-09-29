"""The building blocks of resume import and tailoring, one level below the use cases.

`resume/services.py` decides what may happen and `resume/tasks.py` runs it in
the background; the modules here do the individual pieces and know nothing about
requests, quotas or messages:

* `extractor`       — text out of an uploaded PDF, DOCX or TXT (UC-04.2)
* `deepseek_resume` — the AI call that parses that text into a profile (UC-04.2)
* `importer`        — runs extract -> AI -> store, and holds the readers for the AI's JSON (UC-04.2)
* `tailored`        — the AI call that writes a job-tailored resume, and the Markdown around it (UC-07.1)
* `pdf`             — Markdown to a print-ready PDF (UC-07.3)
"""
