"""Who has portal access, and at what role (UC-08.1, in `staffportal.services`).

Superuser-only, by design: any role that can hand out roles can promote itself,
which makes every other capability boundary decorative.
"""

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import UpdateView

from core.exceptions import Refused

from .. import services
from ..domain import access
from ..forms import StaffAccessForm, StaffRoleForm
from ..models import StaffMember
from .base import PortalActionView, PortalListView, StaffPortalMixin


class TeamListView(PortalListView):
    """Lists portal access and grants it from the same screen — a two-field
    form does not deserve a page of its own."""

    template_name = "staffportal/team_list.html"
    context_object_name = "members"
    required_capability = access.MANAGE_TEAM
    section = "team"
    page_title = "Portal access"
    page_subtitle = "Who can open this portal, and how much of it they can use."

    def get_queryset(self):
        return services.team_members()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = kwargs.get("form") or StaffAccessForm()
        # Staff accounts with no row are real — they read as viewers — so the
        # screen has to show them rather than pretend access is only what is
        # listed here.
        ctx["unmanaged"] = services.unmanaged_staff()
        ctx["role_capabilities"] = services.role_matrix()
        ctx["capability_labels"] = access.CAPABILITY_LABELS
        return ctx

    def post(self, request, *args, **kwargs):
        form = StaffAccessForm(request.POST)
        self.object_list = self.get_queryset()
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        member, _created = services.grant_portal_access(request, form)
        messages.success(request, f"{form.user.email} now has portal access as {member.role}.")
        return redirect("staffportal:team_list")


class TeamUpdateView(StaffPortalMixin, UpdateView):
    model = StaffMember
    form_class = StaffRoleForm
    template_name = "staffportal/team_form.html"
    required_capability = access.MANAGE_TEAM
    section = "team"

    def get_page_title(self):
        return self.object.user.email

    def get_success_url(self):
        return reverse("staffportal:team_list")

    def form_valid(self, form):
        self.object = services.change_staff_role(self.request, form)
        messages.success(self.request, "Role updated.")
        return HttpResponseRedirect(self.get_success_url())


class TeamRevokeView(PortalActionView):
    required_capability = access.MANAGE_TEAM
    section = "team"

    def post(self, request, pk):
        member = get_object_or_404(services.team_members(), pk=pk)
        account = member.user
        try:
            services.revoke_portal_access(request, member)
        except Refused as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, f"Revoked {account.email}'s portal access.")
        return redirect("staffportal:team_list")
