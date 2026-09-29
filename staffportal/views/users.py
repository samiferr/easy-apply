"""Customer accounts: the screens support actually lives in.

Everything destructive is a POST, every mutation writes an audit entry, and the
three actions that can hurt someone — impersonation, deletion, data export —
each need their own capability rather than riding along with "staff". The rules
are in `staffportal.services` (UC-08.2 to UC-08.5 and UC-08.11); these views read
the request and say what happened.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.exceptions import PreconditionFailed, Refused, ServiceError

from .. import services
from ..domain import access
from ..forms import ImpersonationForm, PlanChangeForm, SupportNoteForm
from .base import PortalActionView, PortalListView, StaffPortalMixin


class UserListView(PortalListView):
    template_name = "staffportal/user_list.html"
    context_object_name = "accounts"
    required_capability = access.VIEW_USERS
    section = "users"
    page_title = "Accounts"
    page_subtitle = "Every account, what it is on, and what it has been doing."
    filter_params = ("q", "status", "plan", "activity")

    def get_queryset(self):
        return services.search_accounts(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plans"] = services.list_plans()
        ctx["total_count"] = services.account_count()
        return ctx


class UserExportView(StaffPortalMixin, View):
    """The filtered list as a CSV, streamed."""

    required_capability = access.EXPORT_USER_DATA
    section = "users"

    def get(self, request):
        return services.export_accounts(request, request.GET)


class UserDetailView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/user_detail.html"
    required_capability = access.VIEW_USERS
    section = "users"

    def get_account(self):
        return get_object_or_404(services.accounts_with_subscription(), pk=self.kwargs["pk"])

    def get_page_title(self):
        return self.account.email

    def get_context_data(self, **kwargs):
        self.account = self.get_account()
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.account_overview(self.account, self.request.user))
        subscription = ctx["subscription"]
        ctx["note_form"] = SupportNoteForm()
        ctx["impersonation_form"] = ImpersonationForm()
        ctx["plan_form"] = PlanChangeForm(
            initial={
                "plan": subscription.plan_id if subscription else None,
                "status": subscription.status if subscription else None,
            }
        )
        return ctx


class _AccountActionView(PortalActionView):
    """Shared plumbing for the POST endpoints on the account detail screen."""

    section = "users"

    def get_account(self):
        return get_object_or_404(services.accounts(), pk=self.kwargs["pk"])

    def detail_url(self):
        return reverse("staffportal:user_detail", args=[self.kwargs["pk"]])


class UserSuspendView(_AccountActionView):
    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        reason = request.POST.get("reason", "").strip()
        try:
            services.suspend_account(request, account, reason)
        except Refused as refused:
            messages.error(request, str(refused))
        else:
            messages.success(request, f"Suspended {account.email} and ended their sessions.")
        return redirect(self.detail_url())


class UserReactivateView(_AccountActionView):
    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        services.reactivate_account(request, account)
        messages.success(request, f"Reactivated {account.email}.")
        return redirect(self.detail_url())


class UserPasswordResetView(_AccountActionView):
    """Send the customer the normal reset email."""

    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        try:
            services.send_password_reset(request, account)
        except ServiceError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Reset email sent to {account.email}.")
        return redirect(self.detail_url())


class UserNoteCreateView(_AccountActionView):
    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        form = SupportNoteForm(request.POST)
        if not form.is_valid():
            messages.error(request, "The note can't be empty.")
            return redirect(self.detail_url())
        services.add_support_note(request, account, form)
        messages.success(request, "Note added.")
        return redirect(self.detail_url())


class UserPlanChangeView(_AccountActionView):
    required_capability = access.MANAGE_BILLING

    def post(self, request, pk):
        account = self.get_account()
        form = PlanChangeForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Pick a plan and a status.")
            return redirect(self.detail_url())

        plan = form.cleaned_data["plan"]
        status = form.cleaned_data["status"]
        try:
            services.change_account_plan(request, account, plan, status, form.cleaned_data["note"])
        except PreconditionFailed as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"{account.email} is now on {plan.name} ({status}).")
        return redirect(self.detail_url())


class UserUsageResetView(_AccountActionView):
    """Zero this period's counters — the goodwill gesture after an outage ate
    someone's allowance."""

    required_capability = access.MANAGE_BILLING

    def post(self, request, pk):
        account = self.get_account()
        try:
            services.reset_usage(request, account)
        except PreconditionFailed as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "This period's usage has been reset to zero.")
        return redirect(self.detail_url())


class UserDataExportView(StaffPortalMixin, View):
    """GDPR Art. 20 / CCPA: everything held about one person, as JSON."""

    required_capability = access.EXPORT_USER_DATA
    section = "users"

    def get(self, request, pk):
        account = get_object_or_404(services.accounts(), pk=pk)
        return services.export_account_data(request, account)


class UserDeleteView(StaffPortalMixin, View):
    """Erasure (GDPR Art. 17). Irreversible, so it is typed rather than clicked."""

    required_capability = access.DELETE_USERS
    section = "users"
    template_name = "staffportal/user_delete.html"

    def get_account(self, pk):
        account = get_object_or_404(services.accounts(), pk=pk)
        if account.pk == self.request.user.pk:
            raise Http404
        return account

    def get(self, request, pk):
        account = self.get_account(pk)
        return render(
            request,
            self.template_name,
            {
                "account": account,
                "section": self.section,
                "page_title": f"Delete {account.email}",
                **services.deletion_preview(account, request.user),
            },
        )

    def post(self, request, pk):
        account = self.get_account(pk)
        try:
            email = services.delete_account_as_operator(
                request,
                account,
                request.POST.get("confirm_email", ""),
                request.POST.get("reason", ""),
            )
        except Refused as refused:
            messages.error(request, str(refused))
            return redirect(reverse("staffportal:user_detail", args=[pk]))
        except PreconditionFailed as mismatch:
            messages.error(request, str(mismatch))
            return redirect(reverse("staffportal:user_delete", args=[pk]))
        messages.success(request, f"Deleted {email} and everything belonging to it.")
        return redirect(reverse("staffportal:user_list"))


# --- Impersonation ---------------------------------------------------------
class ImpersonateStartView(_AccountActionView):
    required_capability = access.IMPERSONATE

    def post(self, request, pk):
        account = self.get_account()
        try:
            record = services.start_impersonation(
                request, account, ImpersonationForm(request.POST)
            )
        except ServiceError as error:
            messages.error(request, str(error))
            return redirect(self.detail_url())

        messages.warning(
            request,
            f"You are now signed in as {account.email}. This ends automatically at "
            f"{timezone.localtime(record.expires_at):%H:%M}.",
        )
        return redirect("core:dashboard")


class ImpersonateStopView(View):
    """Hand the session back.

    Deliberately *not* behind `StaffPortalMixin`: while impersonating, the
    request is the customer's, and the portal gate would 404 the very button
    that gets you out.
    """

    http_method_names = ["post"]

    def post(self, request):
        try:
            staff_user = services.stop_impersonation(request)
        except PreconditionFailed:
            return redirect("core:dashboard")
        if staff_user is None:
            messages.info(request, "That impersonation session has ended.")
            return redirect("core:home")
        messages.success(request, f"Back to your own account, {staff_user.email}.")
        return redirect("staffportal:dashboard")


class ImpersonationLogView(PortalListView):
    template_name = "staffportal/impersonation_log.html"
    context_object_name = "sessions"
    required_capability = access.VIEW_AUDIT
    section = "users"
    page_title = "Impersonation log"
    page_subtitle = "Every time a staff account signed in as a customer."

    def get_queryset(self):
        return services.impersonation_sessions()
