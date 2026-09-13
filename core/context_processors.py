from django.conf import settings

from accounts.models import Profile


def site_context(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "LEGAL_ENTITY": settings.LEGAL_ENTITY,
    }


def active_profile(request):
    """Expose the current workspace, and the list to switch between, to every
    template — the switcher lives in the top bar, on every screen."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"active_profile": None, "user_profiles": []}
    return {
        "active_profile": getattr(request, "profile", None),
        "user_profiles": Profile.objects.filter(user=user),
    }
