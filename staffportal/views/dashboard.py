"""The overview screen — the first thing an operator sees (UC-08.1, in
`staffportal.services`)."""

from django.views.generic import TemplateView

from .. import services
from .base import StaffPortalMixin


class DashboardView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/dashboard.html"
    section = "dashboard"
    page_title = "Overview"
    page_subtitle = "Growth, revenue, engagement and the state of the machine."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        days = 30 if self.request.GET.get("range") != "7" else 7
        ctx.update(services.dashboard(self.request.user, days))
        return ctx
