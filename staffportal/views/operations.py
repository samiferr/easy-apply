"""Running the thing: health, the AI queue, and runtime switches (UC-08.7 and
UC-08.9, in `staffportal.services`)."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, TemplateView

from core.exceptions import ServiceError
from core.models import AITask

from .. import services
from ..domain import access
from ..forms import SystemSettingsForm
from .base import PortalActionView, PortalListView, StaffPortalMixin


class HealthView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/health.html"
    required_capability = access.VIEW_OPERATIONS
    section = "operations"
    page_title = "System health"
    page_subtitle = "Is it up, and is it configured the way production should be."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.health_report())
        return ctx


class TaskListView(PortalListView):
    template_name = "staffportal/task_list.html"
    context_object_name = "tasks"
    required_capability = access.VIEW_OPERATIONS
    section = "operations"
    page_title = "AI queue"
    page_subtitle = "Every background job, what it was for, and why it failed."
    filter_params = ("state", "kind", "q")

    def get_queryset(self):
        return services.search_tasks(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["state_choices"] = AITask.STATE_CHOICES
        ctx["kind_choices"] = AITask.KIND_CHOICES
        ctx["ai"] = services.queue_counts()
        return ctx


class TaskDetailView(StaffPortalMixin, TemplateView):
    """One job: progress, timing, what it is about, and what happened to the
    sections it fans out into."""

    template_name = "staffportal/task_detail.html"
    required_capability = access.VIEW_OPERATIONS
    section = "operations"

    def get_page_title(self):
        return f"{self.task.get_kind_display()} #{self.task.pk}"

    def get_context_data(self, **kwargs):
        self.task = get_object_or_404(services.ai_tasks().select_related("user", "profile"), pk=self.kwargs["pk"])
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.task_detail(self.task))
        return ctx


class WorkerListView(StaffPortalMixin, TemplateView):
    """What each Celery worker is running right now."""

    template_name = "staffportal/worker_list.html"
    required_capability = access.VIEW_OPERATIONS
    section = "operations"
    page_title = "Workers"
    page_subtitle = "What the background workers are running right now."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["report"] = services.worker_report()
        return ctx


class TaskExportView(StaffPortalMixin, View):
    required_capability = access.VIEW_OPERATIONS
    section = "operations"

    def get(self, request):
        return services.export_tasks(request, request.GET)


class TaskRetryView(PortalActionView):
    """Re-run a failed job on the customer's behalf."""

    required_capability = access.MANAGE_OPERATIONS
    section = "operations"

    def post(self, request, pk):
        task = get_object_or_404(services.ai_tasks(), pk=pk)
        try:
            services.retry_task(request, task)
        except ServiceError as error:
            messages.error(request, str(error))
            return redirect(self._back(request))

        messages.success(request, "Re-queued. The customer sees it running on their page.")
        return redirect(self._back(request))

    @staticmethod
    def _back(request):
        return request.POST.get("next") or reverse("staffportal:task_list")


class TaskCancelView(PortalActionView):
    """Stop a job that is stuck."""

    required_capability = access.MANAGE_OPERATIONS
    section = "operations"

    def post(self, request, pk):
        task = get_object_or_404(services.ai_tasks(), pk=pk)
        if services.cancel_task(request, task):
            messages.success(request, "Marked as canceled.")
        else:
            messages.info(request, "That job had already finished.")
        return redirect(reverse("staffportal:task_list"))


class SettingsView(StaffPortalMixin, FormView):
    template_name = "staffportal/settings.html"
    form_class = SystemSettingsForm
    required_capability = access.MANAGE_OPERATIONS
    section = "operations"
    page_title = "Runtime settings"
    page_subtitle = "Switches that take effect without a deploy."

    def get_success_url(self):
        return reverse("staffportal:settings")

    def form_valid(self, form):
        changed = services.save_settings(self.request, form.cleaned_data)
        if changed:
            messages.success(self.request, f"Saved. {len(changed)} setting(s) changed.")
        else:
            messages.info(self.request, "Nothing changed.")
        return super().form_valid(form)
