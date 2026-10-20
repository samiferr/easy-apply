"""The building blocks of job analysis, one level below the use cases.

`jobs/services.py` decides what may happen and `jobs/tasks.py` runs it in the
background; the modules here do the individual pieces and know nothing about
requests, quotas or messages:

* `deepseek_client` — the AI calls and their prompts (UC-05.2, UC-05.3, UC-06.3)
* `importer`        — the AI's JSON into JobPost / JobSection / JobElement rows (UC-05.2)
* `matcher`         — one section or row against the profile slice (UC-05.3, UC-05.4, UC-06.3)
"""
