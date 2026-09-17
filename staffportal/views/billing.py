"""Plans, subscriptions and what they add up to."""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from ..forms import PlanForm, SubscriptionForm
from ..models import Plan, Subscription
from ..services import access, audit, exports, metrics
from .base import PortalActionView, PortalListView, StaffPortalMixin


class BillingOverviewView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/billing.html"
    required_capability = access.VIEW_BILLING
    section = "billing"
    page_title = "Billing"
    page_subtitle = "Plans, what each one is worth, and who is on it."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["revenue"] = metrics.revenue()
        ctx["breakdown"] = metrics.plan_breakdown()
        ctx["plans"] = Plan.objects.annotate(
            subscriber_count=Count(
                "subscriptions",
                filter=Q(subscriptions__status__in=Subscription.ENTITLED_STATUSES),
            )
        )
        return ctx


class _PlanFormView(StaffPortalMixin):
    model = Plan
    form_class = PlanForm
    template_name = "staffportal/plan_form.html"
    required_capability = access.MANAGE_BILLING
    section = "billing"
    success_url = reverse_lazy("staffportal:billing")


class PlanCreateView(_PlanFormView, CreateView):
    page_title = "New plan"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(
            self.request, audit.PLAN_CREATED, target=self.object,
            summary=f"Plan created at {self.object.price_display}.",
        )
        messages.success(self.request, f"Created the {self.object.name} plan.")
        return response


class PlanUpdateView(_PlanFormView, UpdateView):
    def get_page_title(self):
        return f"Edit {self.object.name}"

    def form_valid(self, form):
        changed = ", ".join(form.changed_data) or "nothing"
        response = super().form_valid(form)
        audit.log(
            self.request, audit.PLAN_UPDATED, target=self.object,
            summary=f"Changed: {changed}.", fields=form.changed_data,
        )
        messages.success(self.request, f"Saved the {self.object.name} plan.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subscriber_count"] = self.object.subscriptions.filter(
            status__in=Subscription.ENTITLED_STATUSES
        ).count()
        return ctx


class PlanDeleteView(PortalActionView):
    """Retire a plan.

    A plan with subscribers is never deleted — `Subscription.plan` is PROTECTed
    and, more to the point, deleting it would erase what those customers agreed
    to pay. Deactivating is the correct move and the one offered here.
    """

    required_capability = access.MANAGE_BILLING
    section = "billing"

    def post(self, request, pk):
        plan = Plan.objects.filter(pk=pk).first()
        if plan is None:
            return redirect("staffportal:billing")
        if plan.subscriptions.exists():
            plan.is_active = False
            plan.is_default = False
            plan.save(update_fields=["is_active", "is_default", "updated_at"])
            audit.log(
                request, audit.PLAN_UPDATED, target=plan,
                summary="Plan deactivated (it still has subscribers, so it was not deleted).",
            )
            messages.warning(
                request,
                f"{plan.name} still has subscribers, so it was deactivated rather than "
                "deleted. It takes no new sign-ups.",
            )
            return redirect("staffportal:billing")

        name = plan.name
        audit.log(request, audit.PLAN_UPDATED, target=plan, summary="Plan deleted.")
        plan.delete()
        messages.success(request, f"Deleted the {name} plan.")
        return redirect("staffportal:billing")


class SubscriptionListView(PortalListView):
    template_name = "staffportal/subscription_list.html"
    context_object_name = "subscriptions"
    required_capability = access.VIEW_BILLING
    section = "billing"
    page_title = "Subscriptions"
    page_subtitle = "One row per account, with the state its billing is in."
    filter_params = ("q", "status", "plan")

    def get_queryset(self):
        return _subscription_queryset(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plans"] = Plan.objects.all()
        ctx["status_choices"] = Subscription.STATUS_CHOICES
        return ctx


def _subscription_queryset(params):
    queryset = Subscription.objects.select_related("user", "plan")
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(user__email__icontains=query)
            | Q(external_customer_id__icontains=query)
            | Q(external_subscription_id__icontains=query)
        )
    status = params.get("status", "")
    if status in dict(Subscription.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    plan = params.get("plan", "")
    if plan.isdigit():
        queryset = queryset.filter(plan_id=int(plan))
    return queryset


class SubscriptionUpdateView(StaffPortalMixin, UpdateView):
    model = Subscription
    form_class = SubscriptionForm
    template_name = "staffportal/subscription_form.html"
    required_capability = access.MANAGE_BILLING
    section = "billing"

    def get_page_title(self):
        return self.object.user.email

    def get_success_url(self):
        return reverse("staffportal:user_detail", args=[self.object.user_id])

    def form_valid(self, form):
        changed = ", ".join(form.changed_data) or "nothing"
        if "status" in form.changed_data and form.cleaned_data["status"] in (
            Subscription.CANCELED,
            Subscription.EXPIRED,
        ):
            # Churn is measured from this timestamp, so it is set here rather
            # than left to whoever remembers.
            from django.utils import timezone

            form.instance.canceled_at = form.instance.canceled_at or timezone.now()
        response = super().form_valid(form)
        audit.log(
            self.request, audit.SUBSCRIPTION_UPDATED, target=self.object.user,
            summary=f"Subscription changed: {changed}.", fields=form.changed_data,
        )
        messages.success(self.request, "Subscription saved.")
        return response


class SubscriptionExportView(StaffPortalMixin, View):
    required_capability = access.VIEW_BILLING
    section = "billing"

    def get(self, request):
        queryset = _subscription_queryset(request.GET)
        audit.log(
            request, audit.EXPORT_DOWNLOADED,
            summary=f"Subscriptions CSV ({queryset.count()} rows).",
        )
        return exports.stream_csv(
            exports.timestamped("subscriptions"),
            exports.SUBSCRIPTION_HEADER,
            exports.subscription_rows(queryset),
        )
