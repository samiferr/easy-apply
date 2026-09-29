"""Use cases of the public legal pages.

Nothing here touches the database: the pages are static, translated templates,
and the only moving part is who the operator is — configuration, kept in one
place (`settings.LEGAL_ENTITY`) so it is filled in once.

Use cases: docs/use-cases/UC09_COMPLIANCE_LOCALIZATION.md
"""

from django.conf import settings


# UC-09.2 — Dynamic Entity Configuration via Settings
def legal_entity() -> dict:
    """The operator's details (legal name, address, registration, DPO, host, ...).

    Every policy page interpolates these instead of hard-coding them. The
    context processor `core.context_processors.site_context` exposes them to
    every template as `LEGAL_ENTITY`, so the footer and the pages agree.
    """
    return settings.LEGAL_ENTITY


# UC-09.1 — Public Static Legal Framework
def legal_page_context(page_title) -> dict:
    """What a legal page needs besides the operator details: its title, which
    is both its `<h1>` and its breadcrumb (`templates/legal/_legal_base.html`)."""
    return {"page_title": page_title}
