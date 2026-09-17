"""Feature flags."""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from ..forms import FeatureFlagForm
from ..models import FeatureFlag
from ..services import access, audit
from ..services import flags as flag_service
from .base import PortalActionView, PortalListView, StaffPortalMixin


class FlagListView(PortalListView):
    template_name = "staffportal/flag_list.html"
    context_object_name = "flags"
    required_capability = access.VIEW_PORTAL
    section = "flags"
    page_title = "Feature flags"
    page_subtitle = "What is switched on, for whom, without a deploy."

    def get_queryset(self):
        return FeatureFlag.objects.prefetch_related("plans", "users")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # What the signed-in operator would get — a flag list that does not say
        # this invites "it's on, why can't I see it?".
        ctx["my_flags"] = flag_service.enabled_for(self.request.user)
        return ctx


class _FlagFormView(StaffPortalMixin):
    model = FeatureFlag
    form_class = FeatureFlagForm
    template_name = "staffportal/flag_form.html"
    required_capability = access.MANAGE_FLAGS
    section = "flags"
    success_url = reverse_lazy("staffportal:flag_list")

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        audit.log(
            self.request,
            audit.FLAG_CREATED if self.is_create else audit.FLAG_UPDATED,
            target=self.object,
            summary=f"{self.object.key} → {self.object.state_summary}.",
            state=self.object.state,
            percentage=self.object.percentage,
        )
        messages.success(self.request, f"Saved the “{self.object.key}” flag.")
        return response


class FlagCreateView(_FlagFormView, CreateView):
    page_title = "New feature flag"
    is_create = True


class FlagUpdateView(_FlagFormView, UpdateView):
    is_create = False

    def get_page_title(self):
        return self.object.key


class FlagDeleteView(PortalActionView):
    """Deleting a flag retires the feature: evaluation fails closed, so a key
    with no row reads as off everywhere."""

    required_capability = access.MANAGE_FLAGS
    section = "flags"

    def post(self, request, pk):
        flag = FeatureFlag.objects.filter(pk=pk).first()
        if flag is not None:
            key = flag.key
            audit.log(
                request, audit.FLAG_DELETED, target=flag,
                summary=f"Flag {key} deleted — it now evaluates as off everywhere.",
            )
            flag.delete()
            messages.success(request, f"Deleted “{key}”. Code checking it now gets False.")
        return redirect("staffportal:flag_list")
