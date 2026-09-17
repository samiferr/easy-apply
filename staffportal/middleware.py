"""Request-level behaviour the portal owns.

Three small middlewares rather than one: they run at different points, and
folding unrelated work into a single `__call__` is how a maintenance switch
ends up coupled to an analytics write.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model, logout
from django.shortcuts import render
from django.utils import timezone

from .services import impersonation, runtime_settings

User = get_user_model()

#: Paths that stay reachable in maintenance mode: the portal itself (so the
#: switch can be turned back off), auth (so staff can sign in to do it), the
#: language switcher, and assets.
MAINTENANCE_EXEMPT_PREFIXES = ("/staff/", "/admin/", "/accounts/login", "/accounts/logout", "/i18n/", "/static/", "/media/")


class MaintenanceModeMiddleware:
    """Serve a maintenance page to everyone except staff.

    Staff keep full access on purpose: the point of a maintenance window is to
    verify the fix before letting customers back in.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            return render(request, "staffportal/maintenance.html", status=503)
        return self.get_response(request)

    @staticmethod
    def _should_block(request) -> bool:
        if request.path.startswith(MAINTENANCE_EXEMPT_PREFIXES):
            return False
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff:
            return False
        return bool(runtime_settings.get("maintenance_mode"))


class ImpersonationMiddleware:
    """Enforce the lifetime of a "sign in as" session.

    Expiry is checked on the impersonated user's own requests, so a forgotten
    session ends the next time anyone touches it rather than lingering until
    someone remembers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        if impersonation.is_impersonating(request):
            record = impersonation.current_session(request)
            if record is None or not record.is_open:
                from .models import ImpersonationSession

                staff_user = impersonation.stop(request, ImpersonationSession.EXPIRED)
                if staff_user is None:
                    logout(request)
            else:
                request.impersonator = impersonation.actor(request)
                request.impersonation_session = record
        return self.get_response(request)


class LastSeenMiddleware:
    """Keep `User.last_seen_at` roughly current.

    Written at most once every `THROTTLE`, through a targeted UPDATE: activity
    metrics are not worth a row write on every request, and `last_login` alone
    counts a user who signed in in March and has been using the product daily
    ever since as a single visit.
    """

    THROTTLE = timedelta(minutes=5)
    SESSION_KEY = "last_seen_ping"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._touch(request)
        except Exception:  # pragma: no cover — never break a response over a metric
            pass
        return response

    def _touch(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        now = timezone.now()
        last = request.session.get(self.SESSION_KEY)
        if last:
            try:
                if now - datetime.fromisoformat(last) < self.THROTTLE:
                    return
            except (TypeError, ValueError):
                pass
        request.session[self.SESSION_KEY] = now.isoformat()
        User.objects.filter(pk=user.pk).update(last_seen_at=now)
