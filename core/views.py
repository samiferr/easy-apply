from calendar import monthrange
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from jobs.models import JobPost

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

        checklist = [
            (_("Complete your profile"), getattr(user, "profile", None) and user.profile.completion_percent >= 60, "accounts:profile"),
            (_("Set your job preferences"), self._has_preferences(user), "preferences:detail"),
            (_("Add a technical skill"), technical_count > 0, "skills:list"),
            (_("Add a soft skill"), soft_count > 0, "skills:list"),
            (_("Add a language"), language_count > 0, "languages:list"),
            (_("Add your work experience"), experience_count > 0, "experience:list"),
            (_("Add your education or a certificate"), (degree_count + certificate_count) > 0, "education:list"),
        ]
        done_count = sum(1 for _label, done, _url in checklist if done)
        ctx["checklist"] = checklist
        ctx["completion_percent"] = round((done_count / len(checklist)) * 100)

        ctx["recent_jobs"] = (
            JobPost.objects.filter(user=user)
            .prefetch_related("sections__elements")
            .order_by("-created_at")[:5]
        )
        ctx["chart"] = self._jobs_per_day_chart(user)
        ctx["running_tasks"] = (
            AITask.objects.filter(user=user, state__in=[AITask.QUEUED, AITask.RUNNING])
            .order_by("-queued_at")[:4]
        )
        ctx["job_post_count"] = JobPost.objects.filter(user=user).count()
        return ctx

    @staticmethod
    def _has_preferences(user):
        preference = getattr(user, "job_preference", None)
        return bool(preference) and not preference.is_empty

    @staticmethod
    def _jobs_per_day_chart(user):
        """Jobs analyzed per day this month, aggregated in the database and
        rendered as a server-side SVG/CSS chart — no JS charting library."""
        today = timezone.localdate()
        first = today.replace(day=1)
        days_in_month = monthrange(today.year, today.month)[1]

        rows = (
            JobPost.objects.filter(user=user, created_at__date__gte=first)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        )
        counts = {row["day"]: row["count"] for row in rows if row["day"]}

        bars = []
        peak = max(counts.values()) if counts else 0
        for offset in range(days_in_month):
            day = first + timedelta(days=offset)
            count = counts.get(day, 0)
            bars.append(
                {
                    "day": day,
                    "number": day.day,
                    "count": count,
                    # Zero-height bars still get a sliver so the axis reads as a row.
                    "percent": round((count / peak) * 100) if peak else 0,
                    "is_today": day == today,
                    "is_future": day > today,
                }
            )

        return {
            "bars": bars,
            "peak": peak,
            "total": sum(counts.values()),
            "month_label": date_format(first, "F Y"),
            "has_data": bool(counts),
        }


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
