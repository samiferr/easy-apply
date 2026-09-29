"""What the customer-facing shell needs to know about the portal."""

from . import services
from .domain import impersonation


def portal_banners(request):
    """The impersonation banner and any live announcement (UC-08.3, UC-08.8).

    Both live in `base_app.html`, above everything else on the page: a staff
    member inside someone else's account must never be able to forget it, and
    an incident notice nobody scrolls to is not a notice.
    """
    user = getattr(request, "user", None)

    return {
        "impersonator": getattr(request, "impersonator", None),
        "impersonation_session": getattr(request, "impersonation_session", None),
        "is_impersonating": impersonation.is_impersonating(request)
        if hasattr(request, "session")
        else False,
        "live_announcements": services.live_announcements_for(user),
    }
