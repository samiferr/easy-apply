from django.conf import settings

from accounts.models import Profile
from legal.services import legal_entity


def site_context(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "LEGAL_ENTITY": legal_entity(),
        # Show "Continue with Google" only when the OAuth client is configured.
        "GOOGLE_SIGN_IN": bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET),
    }


def active_profile(request):
    """Expose the current workspace, and the list to switch between, to every
    template — the switcher sits at the top of the sidebar, on every screen."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"active_profile": None, "user_profiles": []}
    return {
        "active_profile": getattr(request, "profile", None),
        "user_profiles": Profile.objects.filter(user=user),
    }
