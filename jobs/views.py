from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, View

from core.ai import AIServiceError
from resume.models import TailoredResume

from .forms import JobAnalysisForm
from .models import JobPost
from .services.importer import run_analysis
from .services.matcher import match_requirements_to_profile


class JobPostListView(LoginRequiredMixin, ListView):
    model = JobPost
    template_name = "jobs/job_list.html"
    context_object_name = "job_posts"

    def get_queryset(self):
        return JobPost.objects.filter(user=self.request.user)


class JobPostCreateView(LoginRequiredMixin, CreateView):
    model = JobPost
    form_class = JobAnalysisForm
    template_name = "jobs/job_form.html"

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)
        run_analysis(self.object)
        if self.object.status == JobPost.STATUS_FAILED:
            messages.error(self.request, f"Analysis failed: {self.object.error_message}")
        else:
            messages.success(self.request, f"Analyzed “{self.object.title or self.object.source_url}”.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class JobPostDetailView(LoginRequiredMixin, DetailView):
    model = JobPost
    template_name = "jobs/job_detail.html"
    context_object_name = "job"

    def get_queryset(self):
        return JobPost.objects.filter(user=self.request.user).prefetch_related(
            "categories__requirements"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["match_summary"] = self.object.requirement_match_summary()
        ctx["tailored_resume"] = TailoredResume.objects.filter(job=self.object).first()
        return ctx


class JobPostDeleteView(LoginRequiredMixin, DeleteView):
    model = JobPost
    success_url = reverse_lazy("jobs:list")

    def get_queryset(self):
        return JobPost.objects.filter(user=self.request.user)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Deleted “{self.object.title or self.object.source_url}”.")
        return super().post(request, *args, **kwargs)


class JobPostReanalyzeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        job = get_object_or_404(JobPost, pk=pk, user=request.user)
        run_analysis(job)
        if job.status == JobPost.STATUS_FAILED:
            messages.error(request, f"Re-analysis failed: {job.error_message}")
        else:
            messages.success(request, "Job post re-analyzed.")
        return redirect(job.get_absolute_url())


class JobPostMatchProfileView(LoginRequiredMixin, View):
    def post(self, request, pk):
        job = get_object_or_404(JobPost, pk=pk, user=request.user)
        try:
            result = match_requirements_to_profile(job, request.user)
        except AIServiceError as exc:
            messages.error(request, f"Couldn't match this job to your profile: {exc}")
            return redirect(job.get_absolute_url())

        if result.get("skipped") == "empty_profile":
            messages.warning(
                request,
                "Add some skills, experience or education to your profile first, "
                "then come back to match them against this job.",
            )
        elif result.get("skipped") == "no_requirements":
            messages.warning(request, "This job doesn't have any extracted requirements yet.")
        else:
            messages.success(
                request, f"Matched {result['matched']} of {result['total']} requirements to your profile."
            )
        return redirect(job.get_absolute_url())
