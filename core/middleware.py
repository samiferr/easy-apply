"""Resolves the profile (workspace) every authenticated request works in.

`request.profile` is the single source of truth for scoping: views filter by
it, forms write to it, and the AI answers in its language. It is resolved once
per request here so no view has to remember to do it.
"""

from django.utils.functional import SimpleLazyObject


class ActiveProfileMiddleware:
    """Attach `request.profile` — the user's current workspace.

    Lazy, like `request.user`: an anonymous request (or the admin) never pays
    for the query, and a `SimpleLazyObject` still works as a queryset filter
    value. It is falsy — never an AttributeError — when there is no profile,
    which only happens for anonymous users.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.profile = SimpleLazyObject(lambda: _resolve(request))
        return self.get_response(request)


def _resolve(request):
    from accounts.services import get_active_profile

    return get_active_profile(request)
