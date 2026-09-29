"""Feature flags (UC-08.6, in `staffportal.services`)."""

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from .. import services
from ..domain import access
from ..forms import FeatureFlagForm
from ..models import FeatureFlag
from .base import PortalActionView, PortalListView, StaffPortalMixin


class FlagListView(PortalListView):
    template_name = "staffportal/flag_list.html"
    context_object_name = "flags"
    required_capability = access.VIEW_PORTAL
    section = "flags"
    page_title = "Feature flags"
    page_subtitle = "What is switched on, for whom, without a deploy."

    def get_queryset(self):
        return services.list_flags()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["my_flags"] = services.flags_enabled_for(self.request.user)
        return ctx


class _FlagFormView(StaffPortalMixin):
    model = FeatureFlag
    form_class = FeatureFlagForm
    template_name = "staffportal/flag_form.html"
    required_capability = access.MANAGE_FLAGS
    section = "flags"
    success_url = reverse_lazy("staffportal:flag_list")

    def form_valid(self, form):
        self.object = services.save_flag(self.request, form, created=self.is_create)
        messages.success(self.request, f"Saved the “{self.object.key}” flag.")
        return HttpResponseRedirect(self.get_success_url())


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
        key = services.delete_flag(request, pk)
        if key is not None:
            messages.success(request, f"Deleted “{key}”. Code checking it now gets False.")
        return redirect("staffportal:flag_list")
