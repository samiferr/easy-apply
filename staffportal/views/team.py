"""Who has portal access, and at what role.

Superuser-only, by design: any role that can hand out roles can promote itself,
which makes every other capability boundary decorative.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import UpdateView

from ..forms import StaffAccessForm, StaffRoleForm
from ..models import StaffMember
from ..services import access, audit
from .base import PortalActionView, PortalListView, StaffPortalMixin

User = get_user_model()


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
        return StaffMember.objects.select_related("user", "created_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = kwargs.get("form") or StaffAccessForm()
        # Staff accounts with no row are real — they read as viewers — so the
        # screen has to show them rather than pretend access is only what is
        # listed here.
        ctx["unmanaged"] = User.objects.filter(is_staff=True, staff_member__isnull=True)
        ctx["role_capabilities"] = [
            (role.label, sorted(access.ROLE_CAPABILITIES[role])) for role in access.StaffRole
        ]
        ctx["capability_labels"] = access.CAPABILITY_LABELS
        return ctx

    def post(self, request, *args, **kwargs):
        form = StaffAccessForm(request.POST)
        self.object_list = self.get_queryset()
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        account = form.user
        member, created = StaffMember.objects.update_or_create(
            user=account,
            defaults={
                "role": form.cleaned_data["role"],
                "note": form.cleaned_data["note"],
                "created_by": request.user,
            },
        )
        if not account.is_staff:
            account.is_staff = True
            account.save(update_fields=["is_staff"])
        audit.log(
            request,
            audit.TEAM_GRANTED if created else audit.TEAM_UPDATED,
            target=account,
            summary=f"Portal access as {member.get_role_display()}.",
            role=member.role,
        )
        messages.success(request, f"{account.email} now has portal access as {member.role}.")
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
        response = super().form_valid(form)
        audit.log(
            self.request, audit.TEAM_UPDATED, target=self.object.user,
            summary=f"Role set to {self.object.get_role_display()}.", role=self.object.role,
        )
        messages.success(self.request, "Role updated.")
        return response


class TeamRevokeView(PortalActionView):
    required_capability = access.MANAGE_TEAM
    section = "team"

    def post(self, request, pk):
        member = get_object_or_404(StaffMember, pk=pk)
        account = member.user
        if account.pk == request.user.pk:
            messages.error(request, "You cannot revoke your own access.")
            return redirect("staffportal:team_list")

        member.delete()
        # Revoking the role without clearing `is_staff` would leave a viewer
        # behind, which is not what "revoke" means to the person clicking it.
        if account.is_staff and not account.is_superuser:
            account.is_staff = False
            account.save(update_fields=["is_staff"])
        audit.log(
            request, audit.TEAM_REVOKED, target=account,
            summary="Portal access revoked.",
        )
        messages.success(request, f"Revoked {account.email}'s portal access.")
        return redirect("staffportal:team_list")
