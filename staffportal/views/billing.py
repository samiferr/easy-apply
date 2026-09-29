"""Plans, subscriptions and what they add up to (UC-08.5, in `staffportal.services`)."""

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from .. import services
from ..domain import access
from ..forms import PlanForm, SubscriptionForm
from ..models import Plan, Subscription
from .base import PortalActionView, PortalListView, StaffPortalMixin


class BillingOverviewView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/billing.html"
    required_capability = access.VIEW_BILLING
    section = "billing"
    page_title = "Billing"
    page_subtitle = "Plans, what each one is worth, and who is on it."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.billing_overview())
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
        self.object = services.create_plan(self.request, form)
        messages.success(self.request, f"Created the {self.object.name} plan.")
        return HttpResponseRedirect(self.get_success_url())


class PlanUpdateView(_PlanFormView, UpdateView):
    def get_page_title(self):
        return f"Edit {self.object.name}"

    def form_valid(self, form):
        self.object = services.update_plan(self.request, form)
        messages.success(self.request, f"Saved the {self.object.name} plan.")
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subscriber_count"] = services.entitled_subscriber_count(self.object)
        return ctx


class PlanDeleteView(PortalActionView):
    """Retire a plan: deleted when nobody is on it, deactivated when somebody is."""

    required_capability = access.MANAGE_BILLING
    section = "billing"

    def post(self, request, pk):
        outcome, name = services.retire_plan(request, pk)
        if outcome == services.PLAN_DEACTIVATED:
            messages.warning(
                request,
                f"{name} still has subscribers, so it was deactivated rather than "
                "deleted. It takes no new sign-ups.",
            )
        elif outcome == services.PLAN_DELETED:
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
        return services.search_subscriptions(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plans"] = services.list_plans()
        ctx["status_choices"] = Subscription.STATUS_CHOICES
        return ctx


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
        self.object = services.update_subscription(self.request, form)
        messages.success(self.request, "Subscription saved.")
        return HttpResponseRedirect(self.get_success_url())


class SubscriptionExportView(StaffPortalMixin, View):
    required_capability = access.VIEW_BILLING
    section = "billing"

    def get(self, request):
        return services.export_subscriptions(request, request.GET)
