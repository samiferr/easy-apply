"""What the customer-facing shell needs to know about the portal."""

from .models import Announcement
from .services import impersonation


def portal_banners(request):
    """The impersonation banner and any live announcement.

    Both live in `base_app.html`, above everything else on the page: a staff
    member inside someone else's account must never be able to forget it, and
    an incident notice nobody scrolls to is not a notice.
    """
    user = getattr(request, "user", None)
    authenticated = bool(user and user.is_authenticated)

    audiences = [Announcement.EVERYONE]
    if authenticated:
        audiences.append(Announcement.AUTHENTICATED)
    if authenticated and user.is_staff:
        audiences.append(Announcement.STAFF)

    return {
        "impersonator": getattr(request, "impersonator", None),
        "impersonation_session": getattr(request, "impersonation_session", None),
        "is_impersonating": impersonation.is_impersonating(request)
        if hasattr(request, "session")
        else False,
        "live_announcements": Announcement.objects.live().filter(audience__in=audiences),
    }
