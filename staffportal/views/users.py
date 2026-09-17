"""Customer accounts: the screens support actually lives in.

Everything destructive is a POST, every mutation writes an audit entry, and the
three actions that can hurt someone — impersonation, deletion, data export —
each need their own capability rather than riding along with "staff".
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.forms import PasswordResetForm
from django.conf import settings
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.models import AITask
from jobs.models import JobPost
from resume.models import TailoredResume

from ..forms import ImpersonationForm, PlanChangeForm, SupportNoteForm
from ..models import AuditLog, ImpersonationSession, Plan, SupportNote, UsageRecord
from ..services import access, audit, exports, flags, impersonation, quotas, subscriptions
from .base import PortalActionView, PortalListView, StaffPortalMixin

User = get_user_model()


def _accounts_queryset():
    """One query shape for the list and its CSV export, so the file and the
    screen can never disagree about what a row means."""
    return (
        User.objects.select_related("subscription__plan")
        .annotate(
            profile_count=Count("profiles", distinct=True),
            job_post_count=Count("profiles__job_posts", distinct=True),
        )
        .order_by("-date_joined")
    )


def _apply_filters(queryset, params):
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    status = params.get("status", "")
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "suspended":
        queryset = queryset.filter(is_active=False)
    elif status == "staff":
        queryset = queryset.filter(is_staff=True)

    plan = params.get("plan", "")
    if plan.isdigit():
        queryset = queryset.filter(subscription__plan_id=int(plan))

    activity = params.get("activity", "")
    cutoff = timezone.now() - timedelta(days=30)
    if activity == "recent":
        queryset = queryset.filter(last_seen_at__gte=cutoff)
    elif activity == "dormant":
        queryset = queryset.filter(Q(last_seen_at__lt=cutoff) | Q(last_seen_at__isnull=True))
    return queryset


class UserListView(PortalListView):
    template_name = "staffportal/user_list.html"
    context_object_name = "accounts"
    required_capability = access.VIEW_USERS
    section = "users"
    page_title = "Accounts"
    page_subtitle = "Every account, what it is on, and what it has been doing."
    filter_params = ("q", "status", "plan", "activity")

    def get_queryset(self):
        return _apply_filters(_accounts_queryset(), self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plans"] = Plan.objects.all()
        ctx["total_count"] = User.objects.count()
        return ctx


class UserExportView(StaffPortalMixin, View):
    """The filtered list as a CSV, streamed."""

    required_capability = access.EXPORT_USER_DATA
    section = "users"

    def get(self, request):
        queryset = _apply_filters(_accounts_queryset(), request.GET)
        audit.log(
            request,
            audit.EXPORT_DOWNLOADED,
            summary=f"Accounts CSV ({queryset.count()} rows).",
            filters=dict(request.GET.items()),
        )
        return exports.stream_csv(
            exports.timestamped("accounts"), exports.USER_HEADER, exports.user_rows(queryset)
        )


class UserDetailView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/user_detail.html"
    required_capability = access.VIEW_USERS
    section = "users"

    def get_account(self):
        return get_object_or_404(
            User.objects.select_related("subscription__plan", "staff_member"),
            pk=self.kwargs["pk"],
        )

    def get_page_title(self):
        return self.account.email

    def get_context_data(self, **kwargs):
        self.account = self.get_account()
        ctx = super().get_context_data(**kwargs)
        account = self.account
        profiles = account.profiles.all()

        ctx["account"] = account
        ctx["profiles"] = profiles
        ctx["subscription"] = subscriptions.ensure_subscription(account)
        ctx["allowances"] = quotas.summary(account)
        ctx["profile_limit"], ctx["profile_used"] = quotas.profile_limit(account)
        ctx["quotas_enforced"] = quotas.enforcement_enabled()
        ctx["job_posts"] = (
            JobPost.objects.filter(profile__in=profiles).order_by("-created_at")[:10]
        )
        ctx["job_post_count"] = JobPost.objects.filter(profile__in=profiles).count()
        ctx["tailored_count"] = TailoredResume.objects.filter(profile__in=profiles).count()
        ctx["tasks"] = AITask.objects.filter(user=account).order_by("-queued_at")[:10]
        ctx["notes"] = SupportNote.objects.filter(user=account).select_related("author")
        ctx["note_form"] = SupportNoteForm()
        ctx["enabled_flags"] = sorted(flags.enabled_for(account))
        ctx["impersonations"] = ImpersonationSession.objects.filter(target=account)[:5]
        ctx["audit_entries"] = AuditLog.objects.filter(
            target_type="accounts.user", target_id=str(account.pk)
        )[:10]
        ctx["can_impersonate"], ctx["impersonate_blocked_reason"] = access.can_impersonate(
            self.request.user, account
        )
        ctx["impersonation_form"] = ImpersonationForm()
        ctx["plan_form"] = PlanChangeForm(
            initial={
                "plan": ctx["subscription"].plan_id if ctx["subscription"] else None,
                "status": ctx["subscription"].status if ctx["subscription"] else None,
            }
        )
        return ctx


class _AccountActionView(PortalActionView):
    """Shared plumbing for the POST endpoints on the account detail screen."""

    section = "users"

    def get_account(self):
        return get_object_or_404(User, pk=self.kwargs["pk"])

    def detail_url(self):
        return reverse("staffportal:user_detail", args=[self.kwargs["pk"]])


class UserSuspendView(_AccountActionView):
    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        if account.pk == request.user.pk:
            messages.error(request, "You cannot suspend your own account.")
            return redirect(self.detail_url())
        if account.is_superuser and not request.user.is_superuser:
            messages.error(request, "Only a superuser may suspend a superuser.")
            return redirect(self.detail_url())

        reason = request.POST.get("reason", "").strip()
        account.is_active = False
        account.save(update_fields=["is_active"])
        # Suspension has to end the sessions the account already holds,
        # otherwise it only stops them signing in *again*.
        _flush_sessions(account)
        audit.log(
            request,
            audit.USER_SUSPENDED,
            target=account,
            summary=reason or "Account suspended.",
        )
        messages.success(request, f"Suspended {account.email} and ended their sessions.")
        return redirect(self.detail_url())


class UserReactivateView(_AccountActionView):
    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        account.is_active = True
        account.save(update_fields=["is_active"])
        audit.log(request, audit.USER_REACTIVATED, target=account, summary="Account reactivated.")
        messages.success(request, f"Reactivated {account.email}.")
        return redirect(self.detail_url())


class UserPasswordResetView(_AccountActionView):
    """Send the customer the normal reset email.

    Staff never see or set a customer's password: the reset goes to the address
    on the account, so the customer is the only one who ends up knowing it.
    """

    required_capability = access.MANAGE_USERS

    def post(self, request, pk):
        account = self.get_account()
        form = PasswordResetForm({"email": account.email})
        if not form.is_valid():
            messages.error(request, "That address cannot receive a reset email.")
            return redirect(self.detail_url())
        form.save(
            request=request,
            use_https=request.is_secure(),
            from_email=settings.DEFAULT_FROM_EMAIL,
            email_template_name="accounts/emails/password_reset_email.txt",
            html_email_template_name="accounts/emails/password_reset_email.html",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            extra_email_context={"site_name": settings.SITE_NAME},
        )
        audit.log(
            request,
            audit.USER_PASSWORD_RESET_SENT,
            target=account,
            summary="Password reset email sent.",
        )
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
        note = form.save(commit=False)
        note.user = account
        note.author = request.user
        note.author_email = request.user.email
        note.save()
        audit.log(request, audit.USER_NOTE_ADDED, target=account, summary="Support note added.")
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

        subscription = subscriptions.ensure_subscription(account)
        if subscription is None:
            messages.error(request, "No plans are configured yet.")
            return redirect(self.detail_url())

        before = f"{subscription.plan.name}/{subscription.status}"
        plan = form.cleaned_data["plan"]
        status = form.cleaned_data["status"]
        subscriptions.change_plan(subscription, plan, status=status)
        audit.log(
            request,
            audit.SUBSCRIPTION_UPDATED,
            target=account,
            summary=f"{before} → {plan.name}/{status}. {form.cleaned_data['note']}".strip(),
            plan=plan.slug,
            status=status,
        )
        messages.success(request, f"{account.email} is now on {plan.name} ({status}).")
        return redirect(self.detail_url())


class UserUsageResetView(_AccountActionView):
    """Zero this period's counters — the goodwill gesture after an outage ate
    someone's allowance."""

    required_capability = access.MANAGE_BILLING

    def post(self, request, pk):
        account = self.get_account()
        subscription = subscriptions.ensure_subscription(account)
        if subscription is None:
            messages.error(request, "No plans are configured yet.")
            return redirect(self.detail_url())
        start, _end = subscriptions.current_period(subscription)
        cleared = UsageRecord.objects.filter(user=account, period_start=start).update(count=0)
        audit.log(
            request,
            audit.USAGE_RESET,
            target=account,
            summary=f"Reset {cleared} usage counter(s) for the current period.",
        )
        messages.success(request, "This period's usage has been reset to zero.")
        return redirect(self.detail_url())


class UserDataExportView(StaffPortalMixin, View):
    """GDPR Art. 20 / CCPA: everything held about one person, as JSON."""

    required_capability = access.EXPORT_USER_DATA
    section = "users"

    def get(self, request, pk):
        account = get_object_or_404(User, pk=pk)
        audit.log(
            request,
            audit.USER_EXPORTED,
            target=account,
            summary="Account data export downloaded.",
        )
        return exports.account_export_response(account)


class UserDeleteView(StaffPortalMixin, View):
    """Erasure (GDPR Art. 17). Irreversible, so it is typed rather than clicked.

    The confirmation asks for the email address in full: a delete that is one
    click away from a list row is a delete that eventually happens to the wrong
    account.
    """

    required_capability = access.DELETE_USERS
    section = "users"
    template_name = "staffportal/user_delete.html"

    def get_account(self, pk):
        account = get_object_or_404(User, pk=pk)
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
                "profile_count": account.profiles.count(),
                "job_post_count": JobPost.objects.filter(profile__user=account).count(),
                "blocked": account.is_superuser and not request.user.is_superuser,
            },
        )

    def post(self, request, pk):
        account = self.get_account(pk)
        if account.is_superuser and not request.user.is_superuser:
            messages.error(request, "Only a superuser may delete a superuser account.")
            return redirect(reverse("staffportal:user_detail", args=[pk]))
        if request.POST.get("confirm_email", "").strip().lower() != account.email.lower():
            messages.error(request, "The email address did not match. Nothing was deleted.")
            return redirect(reverse("staffportal:user_delete", args=[pk]))

        email = account.email
        # Audited *before* the delete: the row records a user that is about to
        # stop existing, and `actor` is SET_NULL rather than cascaded, so the
        # entry outlives both accounts.
        audit.log(
            request,
            audit.USER_DELETED,
            target=account,
            summary=f"Account {email} and all of its data deleted.",
            email=email,
            reason=request.POST.get("reason", "")[:200],
        )
        account.delete()
        messages.success(request, f"Deleted {email} and everything belonging to it.")
        return redirect(reverse("staffportal:user_list"))


# --- Impersonation ---------------------------------------------------------
class ImpersonateStartView(_AccountActionView):
    required_capability = access.IMPERSONATE

    def post(self, request, pk):
        account = self.get_account()
        allowed, reason = access.can_impersonate(request.user, account)
        if not allowed:
            messages.error(request, reason)
            return redirect(self.detail_url())

        form = ImpersonationForm(request.POST)
        if not form.is_valid():
            messages.error(request, "A reason is required before impersonating an account.")
            return redirect(self.detail_url())

        record = impersonation.start(request, account, form.cleaned_data["reason"])
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
        if not impersonation.is_impersonating(request):
            return redirect("core:dashboard")
        staff_user = impersonation.stop(request)
        if staff_user is None:
            logout(request)
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
        impersonation.close_expired()
        return ImpersonationSession.objects.select_related("actor", "target")


def _flush_sessions(account) -> None:
    """End every signed-in session belonging to `account`.

    Django keeps sessions as opaque blobs, so there is no index from user to
    session — the honest way is to decode the unexpired ones and drop the
    matches. Fine at this scale; swap for a session backend with a user column
    if the table ever gets large.
    """
    from django.contrib.sessions.models import Session

    target = str(account.pk)
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            if session.get_decoded().get("_auth_user_id") == target:
                session.delete()
        except Exception:  # pragma: no cover — a corrupt session is not our problem
            continue
