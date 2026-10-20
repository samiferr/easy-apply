"""Template helpers for feature flags and the portal's own chrome."""

from django import template

from ..domain import access as access_service
from ..domain import flags as flags_service

register = template.Library()


@register.simple_tag(takes_context=True)
def feature(context, key: str) -> bool:
    """`{% feature "new_matcher" as enabled %}` — evaluated for the current user."""
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    return flags_service.is_enabled(key, user)


@register.simple_tag(takes_context=True)
def can(context, capability: str) -> bool:
    """`{% can "users.delete" as allowed %}` — hides controls the role cannot use.

    The view still enforces it; this only keeps the UI honest about what is
    reachable.
    """
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    return access_service.has_capability(user, capability)


@register.filter
def money(cents) -> str:
    try:
        return f"{int(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return "0.00"


@register.filter
def duration(seconds) -> str:
    """1h 05m / 3m 20s / 45s — for how long something has waited or run."""
    if seconds is None or seconds == "":
        return "—"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


@register.filter
def status_tone(value: str) -> str:
    """Maps a status string onto the badge palette already in the design system."""
    tones = {
        "active": "badge-strong",
        "trialing": "badge-pending",
        "ok": "badge-strong",
        "done": "badge-strong",
        "past_due": "badge-partial",
        "warn": "badge-partial",
        "running": "badge-pending",
        "queued": "badge-pending",
        "canceled": "badge-none",
        "expired": "badge-none",
        "off": "badge-none",
        "failed": "badge-danger",
        "fail": "badge-danger",
    }
    return tones.get(str(value).lower(), "badge-none")


#: The portal's navigation: seven sections, each with the pages it holds. A
#: section with more than one page shows them as tabs under the page title, so
#: the sidebar stays one short list instead of five groups of twelve rows.
#: Each page is (url name, label, capability, url-name prefixes it owns).
PORTAL_NAV = [
    ("dashboard", "Overview", "home", [
        ("staffportal:dashboard", "Overview", access_service.VIEW_PORTAL, ("dashboard",)),
    ]),
    ("users", "Accounts", "users", [
        ("staffportal:user_list", "Accounts", access_service.VIEW_USERS, ("user_", "impersonate_")),
        ("staffportal:impersonation_log", "Impersonation log", access_service.VIEW_AUDIT, ("impersonation_log",)),
    ]),
    ("billing", "Billing", "credit-card", [
        ("staffportal:billing", "Plans & revenue", access_service.VIEW_BILLING, ("billing", "plan_")),
        ("staffportal:subscription_list", "Subscriptions", access_service.VIEW_BILLING, ("subscription_",)),
    ]),
    ("product", "Product", "flag", [
        ("staffportal:flag_list", "Feature flags", access_service.VIEW_PORTAL, ("flag_",)),
        ("staffportal:announcement_list", "Announcements", access_service.VIEW_PORTAL, ("announcement_",)),
    ]),
    ("operations", "Operations", "activity", [
        ("staffportal:health", "System health", access_service.VIEW_OPERATIONS, ("health",)),
        ("staffportal:task_list", "AI queue", access_service.VIEW_OPERATIONS, ("task_", "worker_")),
        ("staffportal:settings", "Runtime settings", access_service.MANAGE_OPERATIONS, ("settings",)),
    ]),
    ("audit", "Audit log", "file-text", [
        ("staffportal:audit_list", "Audit log", access_service.VIEW_AUDIT, ("audit_",)),
    ]),
    ("team", "Portal access", "lock", [
        ("staffportal:team_list", "Portal access", access_service.MANAGE_TEAM, ("team_",)),
    ]),
]

#: Views report the section they belong to; flags and announcements share one.
SECTION_ALIASES = {"flags": "product", "announcements": "product"}


@register.simple_tag(takes_context=True)
def portal_nav(context):
    """The sidebar rows and the current section's tabs, filtered by capability.

    Returns ``{"rows": [...], "tabs": [...]}``; ``tabs`` is empty when the
    current section has a single page.
    """
    from django.urls import reverse

    request = context.get("request")
    user = getattr(request, "user", None)
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") or ""
    current = SECTION_ALIASES.get(context.get("section", ""), context.get("section", ""))
    rows, tabs = [], []
    for key, label, icon, pages in PORTAL_NAV:
        allowed = [page for page in pages if access_service.has_capability(user, page[2])]
        if not allowed:
            continue
        active = key == current
        rows.append({"label": label, "icon": icon, "href": reverse(allowed[0][0]), "active": active})
        if active and len(allowed) > 1:
            tabs = [
                {"label": page_label, "href": reverse(name), "active": url_name.startswith(prefixes)}
                for name, page_label, _, prefixes in allowed
            ]
    return {"rows": rows, "tabs": tabs}
