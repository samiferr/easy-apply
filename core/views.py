from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from . import services


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
        ctx.update(services.build_dashboard(self.request.profile))
        return ctx


class ExportMarkdownView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        content = services.generate_markdown_recap(request.profile)
        response = HttpResponse(content, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="{services.recap_filename(request.profile)}"'
        )
        return response


class ExportPreviewView(LoginRequiredMixin, TemplateView):
    template_name = "core/export_preview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["markdown_content"] = services.generate_markdown_recap(self.request.profile)
        return ctx


class AITaskStatusView(LoginRequiredMixin, View):
    """The polling contract from spec §7.5 — owner-scoped, 404 for anyone else.

    Alpine polls this every 2s (backing off to 5s) and stops on `is_terminal`.
    """

    def get(self, request, pk):
        task = services.task_for_user(request.user, pk)
        if task is None:
            raise Http404
        return JsonResponse(services.task_status(task))
