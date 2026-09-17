"""Template helpers for feature flags and the portal's own chrome."""

from django import template

from ..services import access as access_service
from ..services import flags as flags_service

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
