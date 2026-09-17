"""The overview screen — the first thing an operator sees."""

from django.contrib.auth import get_user_model
from django.views.generic import TemplateView

from core.models import AITask

from ..models import ImpersonationSession
from ..services import access, health, metrics
from .base import StaffPortalMixin

User = get_user_model()


class DashboardView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/dashboard.html"
    section = "dashboard"
    page_title = "Overview"
    page_subtitle = "Growth, revenue, engagement and the state of the machine."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        days = 30 if self.request.GET.get("range") != "7" else 7
        ctx["days"] = days
        ctx.update(metrics.overview(days))

        checks = health.run_checks()
        ctx["health_summary"] = health.summarize(checks)
        # Only the problems here — the full list has its own screen.
        ctx["health_problems"] = [c for c in checks if c.status != health.OK][:4]

        ctx["recent_signups"] = (
            User.objects.select_related("subscription__plan").order_by("-date_joined")[:8]
        )
        ctx["recent_failures"] = (
            AITask.objects.filter(state=AITask.FAILED)
            .select_related("user")
            .order_by("-finished_at")[:5]
        )
        if access.has_capability(self.request.user, access.IMPERSONATE):
            ctx["open_impersonations"] = ImpersonationSession.objects.filter(
                ended_at__isnull=True
            ).order_by("-started_at")[:5]
        return ctx
