from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _, gettext_lazy
from django.views import View
from django.views.generic import DeleteView, ListView

from core.mixins import ConfirmDeleteMixin

from . import services
from .forms import HighlightFormSet, WorkExperienceForm
from .models import WorkExperience


class ExperienceListView(LoginRequiredMixin, ListView):
    model = WorkExperience
    template_name = "experience/experience_list.html"
    context_object_name = "experiences"

    def get_queryset(self):
        return services.list_experiences(self.request.profile)


class BaseExperienceFormView(LoginRequiredMixin, View):
    template_name = "experience/experience_form.html"
    success_url = reverse_lazy("experience:list")

    def get_object(self):
        """Return the WorkExperience being edited, or None when creating."""
        return None

    def get_success_message(self, experience):
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        instance = self.get_object()
        form = WorkExperienceForm(instance=instance)
        formset = HighlightFormSet(instance=instance)
        return render(
            request, self.template_name, {"form": form, "formset": formset, "object": instance}
        )

    def post(self, request, *args, **kwargs):
        instance = self.get_object()
        form = WorkExperienceForm(request.POST, instance=instance)
        formset = HighlightFormSet(
            request.POST, instance=instance or WorkExperience(profile=request.profile)
        )

        if form.is_valid() and formset.is_valid():
            experience = services.save_experience(request.profile, form, formset)
            messages.success(request, self.get_success_message(experience))
            return redirect(self.success_url)

        return render(
            request, self.template_name, {"form": form, "formset": formset, "object": instance}
        )


class ExperienceCreateView(BaseExperienceFormView):
    def get_success_message(self, experience):
        return f"Added your role at {experience.company}."


class ExperienceUpdateView(BaseExperienceFormView):
    def get_object(self):
        return get_object_or_404(
            services.profile_experiences(self.request.profile), pk=self.kwargs["pk"]
        )

    def get_success_message(self, experience):
        return "Work experience updated."


class ExperienceDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = WorkExperience
    success_url = reverse_lazy("experience:list")
    cancel_url_name = "experience:list"
    parent_label = gettext_lazy("Work experience")

    def get_queryset(self):
        return services.profile_experiences(self.request.profile)

    def get_heading(self):
        return _("Delete this role?")

    def get_detail(self):
        return f"{self.object.job_title} — {self.object.company}"

    def form_valid(self, form):
        success_url = self.get_success_url()
        services.remove_experience(self.object)
        return HttpResponseRedirect(success_url)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed {self.object.job_title} at {self.object.company}.")
        return super().post(request, *args, **kwargs)
