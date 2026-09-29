"""Request-level behaviour the portal owns.

Three small middlewares rather than one: they run at different points, and
folding unrelated work into a single `__call__` is how a maintenance switch
ends up coupled to an analytics write. What each one decides lives in
`staffportal.services`; they only decide *when* it runs.
"""

from django.shortcuts import render

from . import services


class MaintenanceModeMiddleware:
    """Serve a maintenance page to everyone except staff (UC-08.7)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if services.maintenance_blocks(request):
            return render(request, "staffportal/maintenance.html", status=503)
        return self.get_response(request)


class ImpersonationMiddleware:
    """Enforce the lifetime of a "sign in as" session (UC-08.3)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        services.apply_impersonation_lifetime(request)
        return self.get_response(request)


class LastSeenMiddleware:
    """Keep `User.last_seen_at` roughly current (UC-08.2), after the response is built."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            services.touch_last_seen(request)
        except Exception:  # pragma: no cover — never break a response over a metric
            pass
        return response
