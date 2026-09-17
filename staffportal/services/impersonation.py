"""Signing in as a customer, safely.

"Reproduce it on my account" is the single most useful support tool there is
and the single easiest one to turn into an incident. The rules that make it
safe are all here rather than spread across views:

* a **reason** is mandatory and recorded;
* the session **expires by itself** (`impersonation_minutes`), because the way
  this goes wrong is someone forgetting they are still inside a customer's
  account;
* the customer-facing app shows a **permanent banner** while it is open;
* an impersonated session **cannot reach the portal**, cannot change the
  account's credentials, and cannot delete the account — otherwise
  impersonation is a way to launder an action you are not allowed to take;
* both ends are written to the audit trail.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.utils import timezone

from ..models import ImpersonationSession
from . import audit, runtime_settings

#: The signed-in staff account, parked while their session belongs to someone else.
SESSION_ACTOR_KEY = "impersonator_id"
SESSION_RECORD_KEY = "impersonation_id"

User = get_user_model()


def _backend() -> str:
    backends = getattr(settings, "AUTHENTICATION_BACKENDS", None) or [
        "django.contrib.auth.backends.ModelBackend"
    ]
    return backends[0]


def is_impersonating(request) -> bool:
    return bool(getattr(request, "session", None) and request.session.get(SESSION_ACTOR_KEY))


def current_session(request) -> ImpersonationSession | None:
    record_id = request.session.get(SESSION_RECORD_KEY)
    if not record_id:
        return None
    return ImpersonationSession.objects.filter(pk=record_id).first()


def actor(request):
    """The staff account behind an impersonated session, if any."""
    actor_id = request.session.get(SESSION_ACTOR_KEY)
    if not actor_id:
        return None
    return User.objects.filter(pk=actor_id).first()


def start(request, target, reason: str) -> ImpersonationSession:
    """Swap the session over to `target` and open an audit record.

    `login()` rotates the session, so the bookkeeping keys are written after it
    — writing them first would silently drop them.
    """
    staff_user = request.user
    minutes = max(1, int(runtime_settings.get("impersonation_minutes")))
    record = ImpersonationSession.objects.create(
        actor=staff_user,
        actor_email=staff_user.email,
        target=target,
        target_email=target.email,
        reason=reason[:200],
        ip_address=audit.client_ip(request),
        expires_at=timezone.now() + timedelta(minutes=minutes),
    )
    audit.log(
        request,
        audit.IMPERSONATION_STARTED,
        target=target,
        summary=f"Impersonation started: {reason[:180]}",
        actor=staff_user,
        session_id=record.pk,
        minutes=minutes,
    )

    login(request, target, backend=_backend())
    request.session[SESSION_ACTOR_KEY] = staff_user.pk
    request.session[SESSION_RECORD_KEY] = record.pk
    return record


def stop(request, reason: str = ImpersonationSession.MANUAL):
    """Hand the session back to the staff account. Returns them, or None.

    Returning None means the parked account is gone or has since been stripped
    of staff access; the caller logs the session out rather than leaving it
    sitting inside the customer's account.
    """
    record = current_session(request)
    staff_user = actor(request)

    if record is not None:
        record.close(reason)

    if staff_user is None or not staff_user.is_staff or not staff_user.is_active:
        return None

    target = request.user if request.user.is_authenticated else None
    login(request, staff_user, backend=_backend())
    audit.log(
        request,
        audit.IMPERSONATION_ENDED,
        target=target,
        summary=f"Impersonation ended ({reason}).",
        actor=staff_user,
        session_id=record.pk if record else None,
    )
    return staff_user


def close_expired() -> int:
    """Close records whose window has passed. The session itself is ended by the
    middleware on the impersonated user's next request; this keeps the list
    screen honest for sessions that were simply abandoned."""
    now = timezone.now()
    stale = ImpersonationSession.objects.filter(ended_at__isnull=True, expires_at__lte=now)
    return stale.update(ended_at=now, ended_reason=ImpersonationSession.EXPIRED)
