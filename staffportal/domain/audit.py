"""Writing the audit trail.

Every mutating action in the portal calls `log()`. The entry keeps a readable
copy of who and what — email address, target label — because the account it
describes may be gone by the time anyone reads it back, and that is precisely
the entry someone will come asking about.
"""

from django.conf import settings

from ..models import AuditLog

# Action slugs. Kept as constants so the audit filter can offer a closed list
# instead of whatever strings happen to be in the table.
USER_SUSPENDED = "user.suspended"
USER_REACTIVATED = "user.reactivated"
USER_DELETED = "user.deleted"
USER_EXPORTED = "user.exported"
USER_PASSWORD_RESET_SENT = "user.password_reset_sent"
USER_NOTE_ADDED = "user.note_added"
IMPERSONATION_STARTED = "impersonation.started"
IMPERSONATION_ENDED = "impersonation.ended"
PLAN_CREATED = "plan.created"
PLAN_UPDATED = "plan.updated"
SUBSCRIPTION_UPDATED = "subscription.updated"
USAGE_RESET = "usage.reset"
FLAG_CREATED = "flag.created"
FLAG_UPDATED = "flag.updated"
FLAG_DELETED = "flag.deleted"
ANNOUNCEMENT_CREATED = "announcement.created"
ANNOUNCEMENT_UPDATED = "announcement.updated"
ANNOUNCEMENT_DELETED = "announcement.deleted"
SETTING_UPDATED = "setting.updated"
TASK_RETRIED = "task.retried"
TASK_CANCELED = "task.canceled"
TEAM_GRANTED = "team.granted"
TEAM_UPDATED = "team.updated"
TEAM_REVOKED = "team.revoked"
EXPORT_DOWNLOADED = "export.downloaded"

ACTION_CHOICES = [
    (value, value)
    for value in sorted(
        {
            USER_SUSPENDED, USER_REACTIVATED, USER_DELETED, USER_EXPORTED,
            USER_PASSWORD_RESET_SENT, USER_NOTE_ADDED,
            IMPERSONATION_STARTED, IMPERSONATION_ENDED,
            PLAN_CREATED, PLAN_UPDATED, SUBSCRIPTION_UPDATED, USAGE_RESET,
            FLAG_CREATED, FLAG_UPDATED, FLAG_DELETED,
            ANNOUNCEMENT_CREATED, ANNOUNCEMENT_UPDATED, ANNOUNCEMENT_DELETED,
            SETTING_UPDATED, TASK_RETRIED, TASK_CANCELED,
            TEAM_GRANTED, TEAM_UPDATED, TEAM_REVOKED, EXPORT_DOWNLOADED,
        }
    )
]


def client_ip(request) -> str | None:
    """The caller's address.

    `X-Forwarded-For` is only read when the deployment says its proxy sets it
    (`STAFF_PORTAL_TRUST_X_FORWARDED_FOR`). Trusting it unconditionally lets
    anyone write whatever they like into the audit trail's `ip_address`.
    """
    if request is None:
        return None
    if getattr(settings, "STAFF_PORTAL_TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def describe(target) -> tuple[str, str, str]:
    """(type, id, label) for any model instance, or empty strings for None."""
    if target is None:
        return "", "", ""
    meta = getattr(target, "_meta", None)
    target_type = meta.label_lower if meta else target.__class__.__name__.lower()
    return target_type, str(getattr(target, "pk", "") or ""), str(target)[:200]


def log(request, action: str, *, target=None, summary: str = "", actor=None, **metadata):
    """Append one entry. Never raises into the caller's code path.

    Auditing is a side effect of the action, not a precondition for it: a
    logging failure must not turn a successful suspension into a 500. It is
    logged loudly instead.
    """
    from logging import getLogger

    target_type, target_id, target_repr = describe(target)
    actor = actor or (getattr(request, "user", None) if request else None)
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None

    try:
        return AuditLog.objects.create(
            actor=actor,
            actor_email=getattr(actor, "email", "") or "",
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_repr=target_repr,
            summary=summary[:300],
            metadata=metadata or {},
            while_impersonating=bool(
                request is not None and request.session.get("impersonator_id")
            ),
            ip_address=client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
        )
    except Exception:  # pragma: no cover — defensive
        getLogger(__name__).exception("Could not write audit entry for %s", action)
        return None
