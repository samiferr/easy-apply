"""The gate every portal screen goes through, and the shared plumbing behind it.

Three rules are enforced here and nowhere else, so no screen can forget one:

1. **A non-staff visitor gets a 404, not a 403.** A 403 confirms the portal
   exists at this URL; a 404 says nothing. Staff who are merely missing a
   capability *do* get a 403 — they already know it is here, and a silent 404
   would just look like a broken link.
2. **An impersonated session can never reach the portal.** Otherwise "sign in
   as a customer" becomes a way to act as staff through a session that the
   audit trail attributes to the customer.
3. **Nothing here is cached or indexed.** Every page is somebody's personal
   data.

The decision for 1 and 2 is `staffportal.services.portal_gate` (UC-08.1); this
module only turns it into a redirect, a 404 or a 403 page.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import ListView

from .. import services
from ..domain import access


@method_decorator(never_cache, name="dispatch")
class StaffPortalMixin(LoginRequiredMixin):
    #: The capability a visitor needs for this screen.
    required_capability = access.VIEW_PORTAL
    #: Which sidebar group to highlight.
    section = ""
    page_title = ""
    page_subtitle = ""

    def dispatch(self, request, *args, **kwargs):
        gate = services.portal_gate(request, self.required_capability)
        if gate == services.LOGIN:
            return self.handle_no_permission()
        if gate == services.HIDDEN:
            raise Http404
        if gate == services.FORBIDDEN:
            return render(
                request,
                "staffportal/forbidden.html",
                services.forbidden_context(request.user, self.required_capability, self.section),
                status=403,
            )

        response = super().dispatch(request, *args, **kwargs)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    def get_page_title(self):
        return self.page_title

    def get_page_subtitle(self):
        return self.page_subtitle

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("page_title", self.get_page_title())
        ctx.setdefault("page_subtitle", self.get_page_subtitle())
        ctx["section"] = self.section
        ctx.update(services.portal_context(self.request.user))
        return ctx


class PortalActionView(StaffPortalMixin, View):
    """A POST-only endpoint: suspend, retry, revoke, ...

    Everything that changes state is a POST behind CSRF. A staff action on a GET
    is a link someone can be tricked into following.
    """

    http_method_names = ["post"]


class PortalListView(StaffPortalMixin, ListView):
    paginate_by = 50
    #: Query-string keys the template's pagination links must carry through, so
    #: page 2 of a filtered list is still filtered.
    filter_params: tuple = ()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["querystring"] = params.urlencode()
        ctx["filters"] = {key: self.request.GET.get(key, "") for key in self.filter_params}
        return ctx
