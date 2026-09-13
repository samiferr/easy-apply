from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View

from .forms import BenefitPreferenceForm, JobPreferenceForm
from .models import BenefitPreference, get_or_create_preference


class JobPreferenceView(LoginRequiredMixin, View):
    """The "Job preferences" profile tab: the scalar form plus the benefit rows."""

    template_name = "preferences/job_preference.html"

    def get_context(self, request, form=None, benefit_form=None):
        preference = get_or_create_preference(request.profile)
        return {
            "preference": preference,
            "form": form or JobPreferenceForm(instance=preference),
            "benefit_form": benefit_form or BenefitPreferenceForm(preference=preference),
            "benefits": preference.benefits.all(),
            "active_tab": "preferences",
        }

    def get(self, request):
        return render(request, self.template_name, self.get_context(request))

    def post(self, request):
        preference = get_or_create_preference(request.profile)
        form = JobPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            form.save()
            messages.success(request, _("Job preferences saved."))
            return redirect("preferences:detail")
        return render(request, self.template_name, self.get_context(request, form=form))


class BenefitCreateView(LoginRequiredMixin, View):
    def post(self, request):
        preference = get_or_create_preference(request.profile)
        form = BenefitPreferenceForm(request.POST, preference=preference)
        if form.is_valid():
            benefit = form.save(commit=False)
            benefit.preference = preference
            benefit.save()
            messages.success(request, _("Added “%(name)s” to your preferences.") % {"name": benefit.name})
        else:
            for error in form.errors.values():
                messages.error(request, error[0])
        return redirect("preferences:detail")


class BenefitUpdateView(LoginRequiredMixin, View):
    """Inline importance change from the benefits table."""

    def post(self, request, pk):
        benefit = get_object_or_404(
            BenefitPreference, pk=pk, preference__profile=request.profile
        )
        importance = request.POST.get("importance")
        valid = {choice[0] for choice in BenefitPreference.IMPORTANCE_CHOICES}
        if importance in valid:
            benefit.importance = importance
            benefit.save(update_fields=["importance"])
        return redirect(f"{reverse('preferences:detail')}#benefits")


class BenefitDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        benefit = get_object_or_404(
            BenefitPreference, pk=pk, preference__profile=request.profile
        )
        name = benefit.name
        benefit.delete()
        messages.info(request, _("Removed “%(name)s”.") % {"name": name})
        return redirect(f"{reverse('preferences:detail')}#benefits")
