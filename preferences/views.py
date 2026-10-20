from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View

from . import services
from .forms import BenefitPreferenceForm, JobPreferenceForm

CONFIRM_DELETE_TEMPLATE = "core/confirm_delete.html"


class JobPreferenceView(LoginRequiredMixin, View):
    """The "Job preferences" profile tab: the scalar form plus the benefit rows."""

    template_name = "preferences/job_preference.html"

    def get_context(self, request, form=None, benefit_form=None):
        screen = services.preference_screen(request.profile)
        preference = screen["preference"]
        return {
            "preference": preference,
            "form": form or JobPreferenceForm(instance=preference),
            "benefit_form": benefit_form or BenefitPreferenceForm(preference=preference),
            "benefits": screen["benefits"],
        }

    def get(self, request):
        return render(request, self.template_name, self.get_context(request))

    def post(self, request):
        preference = services.get_or_create_preference(request.profile)
        form = JobPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            services.save_preferences(form)
            messages.success(request, _("Job preferences saved."))
            return redirect("preferences:detail")
        return render(request, self.template_name, self.get_context(request, form=form))


class BenefitCreateView(LoginRequiredMixin, View):
    def post(self, request):
        preference = services.get_or_create_preference(request.profile)
        form = BenefitPreferenceForm(request.POST, preference=preference)
        if form.is_valid():
            benefit = services.add_benefit(preference, form)
            messages.success(request, _("Added “%(name)s” to your preferences.") % {"name": benefit.name})
        else:
            for error in form.errors.values():
                messages.error(request, error[0])
        return redirect("preferences:detail")


class BenefitUpdateView(LoginRequiredMixin, View):
    """Inline importance change from the benefits table."""

    def post(self, request, pk):
        benefit = get_object_or_404(services.profile_benefits(request.profile), pk=pk)
        services.change_benefit_importance(benefit, request.POST.get("importance"))
        return redirect(f"{reverse('preferences:detail')}#benefits")


class BenefitDeleteView(LoginRequiredMixin, View):
    def get_benefit(self, request, pk):
        return get_object_or_404(services.profile_benefits(request.profile), pk=pk)

    def get(self, request, pk):
        benefit = self.get_benefit(request, pk)
        cancel_url = f"{reverse('preferences:detail')}#benefits"
        return render(
            request,
            CONFIRM_DELETE_TEMPLATE,
            {
                "page_title": _("Delete this benefit?"),
                "heading": _("Delete this benefit?"),
                "detail": benefit.name,
                "cancel_url": cancel_url,
                "parent_crumbs": [{"label": _("Job preferences"), "url": cancel_url}],
            },
        )

    def post(self, request, pk):
        benefit = self.get_benefit(request, pk)
        name = benefit.name
        services.remove_benefit(benefit)
        messages.info(request, _("Removed “%(name)s”.") % {"name": name})
        return redirect(f"{reverse('preferences:detail')}#benefits")
