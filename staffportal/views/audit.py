"""The audit trail: read-only, filterable, exportable."""

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.views import View

from ..models import AuditLog
from ..services import access, exports
from ..services import audit as audit_service
from .base import PortalListView, StaffPortalMixin

User = get_user_model()


def _audit_queryset(params):
    queryset = AuditLog.objects.select_related("actor")
    action = params.get("action", "")
    if action:
        queryset = queryset.filter(action=action)
    actor = params.get("actor", "")
    if actor.isdigit():
        queryset = queryset.filter(actor_id=int(actor))
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(actor_email__icontains=query)
            | Q(target_repr__icontains=query)
            | Q(summary__icontains=query)
        )
    impersonated = params.get("impersonated", "")
    if impersonated == "1":
        queryset = queryset.filter(while_impersonating=True)
    return queryset


class AuditListView(PortalListView):
    template_name = "staffportal/audit_list.html"
    context_object_name = "entries"
    required_capability = access.VIEW_AUDIT
    section = "audit"
    page_title = "Audit log"
    page_subtitle = "Every change a staff account made, and from where."
    filter_params = ("action", "actor", "q", "impersonated")

    def get_queryset(self):
        return _audit_queryset(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action_choices"] = audit_service.ACTION_CHOICES
        ctx["actors"] = User.objects.filter(staff_actions__isnull=False).distinct()
        return ctx


class AuditExportView(StaffPortalMixin, View):
    required_capability = access.VIEW_AUDIT
    section = "audit"

    def get(self, request):
        queryset = _audit_queryset(request.GET)
        # Exporting the audit log is itself audited. It has to be: "who took a
        # copy of the trail" is exactly the question the trail is kept for.
        audit_service.log(
            request, audit_service.EXPORT_DOWNLOADED,
            summary=f"Audit log CSV ({queryset.count()} rows).",
        )
        return exports.stream_csv(
            exports.timestamped("audit-log"), exports.AUDIT_HEADER, exports.audit_rows(queryset)
        )
