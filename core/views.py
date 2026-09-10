from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .models import AITask
from .utils import generate_markdown_recap, recap_filename


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:dashboard")
        return super().get(request, *args, **kwargs)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        soft_count = user.skills.filter(category__kind="soft").count()
        technical_count = user.skills.filter(category__kind="technical").count()
        language_count = user.languages.count()
        experience_count = user.experiences.count()
        degree_count = user.degrees.count()
        certificate_count = user.certificates.count()
        job_post_count = user.job_posts.count()

        checklist = [
            ("Complete your profile", getattr(user, "profile", None) and user.profile.completion_percent >= 60, "accounts:profile"),
            ("Add at least one soft skill", soft_count > 0, "skills:list"),
            ("Add at least one technical skill", technical_count > 0, "skills:list"),
            ("Add a language", language_count > 0, "languages:list"),
            ("Add your work experience", experience_count > 0, "experience:list"),
            ("Add your education or a certificate", (degree_count + certificate_count) > 0, "education:list"),
        ]
        done_count = sum(1 for _, done, _ in checklist if done)
        ctx["checklist"] = checklist
        ctx["completion_percent"] = round((done_count / len(checklist)) * 100)

        ctx["stats"] = [
            {"label": "Job posts analyzed", "value": job_post_count, "url": "jobs:list"},
            {"label": "Soft skills", "value": soft_count, "url": "skills:list"},
            {"label": "Technical skills", "value": technical_count, "url": "skills:list"},
            {"label": "Languages", "value": language_count, "url": "languages:list"},
            {"label": "Work experiences", "value": experience_count, "url": "experience:list"},
            {"label": "Degrees", "value": degree_count, "url": "education:list"},
            {"label": "Certificates", "value": certificate_count, "url": "education:list"},
        ]
        ctx["recent_experiences"] = user.experiences.order_by("-is_current", "-start_date")[:3]
        return ctx


class ExportMarkdownView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        content = generate_markdown_recap(request.user)
        response = HttpResponse(content, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{recap_filename(request.user)}"'
        return response


class ExportPreviewView(LoginRequiredMixin, TemplateView):
    template_name = "core/export_preview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["markdown_content"] = generate_markdown_recap(self.request.user)
        return ctx


class AITaskStatusView(LoginRequiredMixin, View):
    """The polling contract from spec §7.5 — owner-scoped, 404 for anyone else.

    Alpine polls this every 2s (backing off to 5s) and stops on `is_terminal`.
    """

    def get(self, request, pk):
        task = AITask.objects.filter(pk=pk, user=request.user).first()
        if task is None:
            raise Http404

        return JsonResponse(
            {
                "id": task.pk,
                "kind": task.kind,
                "state": task.state,
                "percent": task.percent,
                "indeterminate": task.is_indeterminate,
                "current_step": task.current_step,
                "steps_done": task.steps_done,
                "steps_total": task.steps_total,
                "error_message": task.error_message,
                "is_terminal": task.is_terminal,
                "redirect_url": self._redirect_url(task),
            }
        )

    def _redirect_url(self, task):
        """Where the browser should go once a terminal task finishes."""
        if task.state != AITask.DONE:
            return None
        target = task.target
        if target is None:
            return None
        if task.kind == AITask.RESUME_IMPORT:
            return reverse("resume:review", args=[target.pk])
        if task.kind == AITask.TAILORED_RESUME:
            return reverse("resume:tailored", args=[target.job_id])
        return None
