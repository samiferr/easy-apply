from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DeleteView, ListView

from .forms import HighlightFormSet, WorkExperienceForm
from .models import WorkExperience


class ExperienceListView(LoginRequiredMixin, ListView):
    extra_context = {"active_tab": "experience"}
    model = WorkExperience
    template_name = "experience/experience_list.html"
    context_object_name = "experiences"

    def get_queryset(self):
        return WorkExperience.objects.filter(profile=self.request.profile).prefetch_related(
            "highlights"
        )


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
            experience = form.save(commit=False)
            experience.profile = request.profile
            experience.save()
            formset.instance = experience
            formset.save()
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
            WorkExperience, pk=self.kwargs["pk"], profile=self.request.profile
        )

    def get_success_message(self, experience):
        return "Work experience updated."


class ExperienceDeleteView(LoginRequiredMixin, DeleteView):
    model = WorkExperience
    success_url = reverse_lazy("experience:list")

    def get_queryset(self):
        return WorkExperience.objects.filter(profile=self.request.profile)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed {self.object.job_title} at {self.object.company}.")
        return super().post(request, *args, **kwargs)
