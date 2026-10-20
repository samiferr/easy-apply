"""The audit trail: read-only, filterable, exportable (UC-08.10, in
`staffportal.services`)."""

from django.views import View

from .. import services
from ..domain import access
from ..domain import audit as audit_service
from .base import PortalListView, StaffPortalMixin


class AuditListView(PortalListView):
    template_name = "staffportal/audit_list.html"
    context_object_name = "entries"
    required_capability = access.VIEW_AUDIT
    section = "audit"
    page_title = "Audit log"
    page_subtitle = "Every change a staff account made, and from where."
    filter_params = ("action", "actor", "q", "impersonated")

    def get_queryset(self):
        return services.search_audit(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action_choices"] = audit_service.ACTION_CHOICES
        ctx["actors"] = services.audit_actors()
        return ctx


class AuditExportView(StaffPortalMixin, View):
    required_capability = access.VIEW_AUDIT
    section = "audit"

    def get(self, request):
        return services.export_audit(request, request.GET)
