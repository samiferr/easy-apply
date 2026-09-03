from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import WorkExperienceForm
from .models import WorkExperience


class ExperienceListView(LoginRequiredMixin, ListView):
    model = WorkExperience
    template_name = "experience/experience_list.html"
    context_object_name = "experiences"

    def get_queryset(self):
        return WorkExperience.objects.filter(user=self.request.user)


class ExperienceFormMixin(LoginRequiredMixin):
    model = WorkExperience
    form_class = WorkExperienceForm
    template_name = "experience/experience_form.html"
    success_url = reverse_lazy("experience:list")

    def get_queryset(self):
        return WorkExperience.objects.filter(user=self.request.user)


class ExperienceCreateView(ExperienceFormMixin, CreateView):
    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, f"Added your role at {form.instance.company}.")
        return super().form_valid(form)


class ExperienceUpdateView(ExperienceFormMixin, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Work experience updated.")
        return super().form_valid(form)


class ExperienceDeleteView(LoginRequiredMixin, DeleteView):
    model = WorkExperience
    success_url = reverse_lazy("experience:list")

    def get_queryset(self):
        return WorkExperience.objects.filter(user=self.request.user)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed {self.object.job_title} at {self.object.company}.")
        return super().post(request, *args, **kwargs)
