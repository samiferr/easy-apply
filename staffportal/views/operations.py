"""Running the thing: health, the AI queue, and runtime switches."""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from core.models import AITask

from ..forms import SystemSettingsForm
from ..services import access, audit, exports, health
from .base import PortalActionView, PortalListView, StaffPortalMixin


class HealthView(StaffPortalMixin, TemplateView):
    template_name = "staffportal/health.html"
    required_capability = access.VIEW_OPERATIONS
    section = "operations"
    page_title = "System health"
    page_subtitle = "Is it up, and is it configured the way production should be."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        checks = health.run_checks()
        ctx["summary"] = health.summarize(checks)
        grouped = {}
        for check in checks:
            grouped.setdefault(check.group, []).append(check)
        ctx["grouped_checks"] = list(grouped.items())
        ctx["checked_at"] = timezone.now()
        return ctx


def _task_queryset(params):
    queryset = AITask.objects.select_related("user", "profile").order_by("-queued_at")
    state = params.get("state", "")
    if state in dict(AITask.STATE_CHOICES):
        queryset = queryset.filter(state=state)
    kind = params.get("kind", "")
    if kind in dict(AITask.KIND_CHOICES):
        queryset = queryset.filter(kind=kind)
    query = params.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(user__email__icontains=query) | Q(error_message__icontains=query)
        )
    return queryset


class TaskListView(PortalListView):
    template_name = "staffportal/task_list.html"
    context_object_name = "tasks"
    required_capability = access.VIEW_OPERATIONS
    section = "operations"
    page_title = "AI queue"
    page_subtitle = "Every background job, what it was for, and why it failed."
    filter_params = ("state", "kind", "q")

    def get_queryset(self):
        return _task_queryset(self.request.GET)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["state_choices"] = AITask.STATE_CHOICES
        ctx["kind_choices"] = AITask.KIND_CHOICES
        ctx["ai"] = _queue_counts()
        return ctx


def _queue_counts() -> dict:
    return {
        "queued": AITask.objects.filter(state=AITask.QUEUED).count(),
        "running": AITask.objects.filter(state=AITask.RUNNING).count(),
        "failed": AITask.objects.filter(state=AITask.FAILED).count(),
    }


class TaskExportView(StaffPortalMixin, View):
    required_capability = access.VIEW_OPERATIONS
    section = "operations"

    def get(self, request):
        queryset = _task_queryset(request.GET)
        audit.log(
            request, audit.EXPORT_DOWNLOADED,
            summary=f"AI queue CSV ({queryset.count()} rows).",
        )
        return exports.stream_csv(
            exports.timestamped("ai-tasks"), exports.TASK_HEADER, exports.task_rows(queryset)
        )


class TaskRetryView(PortalActionView):
    """Re-run a failed job on the customer's behalf.

    Dispatch goes through the same `enqueue_*` helpers the product uses, so a
    retry from here is indistinguishable from the customer pressing the button
    — no second code path to keep correct.
    """

    required_capability = access.MANAGE_OPERATIONS
    section = "operations"

    def post(self, request, pk):
        task = get_object_or_404(AITask, pk=pk)
        target = task.target
        if target is None:
            messages.error(request, "The object this job was about no longer exists.")
            return redirect(self._back(request))

        try:
            self._requeue(task, target)
        except Exception as exc:
            messages.error(request, f"Could not re-queue: {exc}")
            return redirect(self._back(request))

        audit.log(
            request, audit.TASK_RETRIED, target=task,
            summary=f"{task.get_kind_display()} re-queued for {task.user.email}.",
            kind=task.kind,
        )
        messages.success(request, "Re-queued. The customer sees it running on their page.")
        return redirect(self._back(request))

    @staticmethod
    def _requeue(task, target):
        from jobs.tasks import enqueue_full_match, enqueue_job_analysis
        from resume.tasks import enqueue_resume_analysis, enqueue_tailored_resume

        if task.kind == AITask.JOB_ANALYSIS:
            return enqueue_job_analysis(target)
        if task.kind == AITask.JOB_MATCH:
            return enqueue_full_match(target)
        if task.kind == AITask.RESUME_IMPORT:
            return enqueue_resume_analysis(target)
        if task.kind == AITask.TAILORED_RESUME:
            # The tailored-resume pipeline is keyed on the job, not the draft.
            return enqueue_tailored_resume(target.job)
        raise ValueError(f"No retry path for {task.kind}")

    @staticmethod
    def _back(request):
        return request.POST.get("next") or reverse("staffportal:task_list")


class TaskCancelView(PortalActionView):
    """Stop a job that is stuck.

    Only the record is closed — a Celery worker already inside the task keeps
    running until its time limit. That is honest: revoking mid-flight would
    leave half-written analysis behind.
    """

    required_capability = access.MANAGE_OPERATIONS
    section = "operations"

    def post(self, request, pk):
        task = get_object_or_404(AITask, pk=pk)
        if task.is_terminal:
            messages.info(request, "That job had already finished.")
            return redirect(reverse("staffportal:task_list"))
        task.state = AITask.CANCELED
        task.finished_at = timezone.now()
        task.save(update_fields=["state", "finished_at", "updated_at"])
        audit.log(
            request, audit.TASK_CANCELED, target=task,
            summary=f"{task.get_kind_display()} canceled.", kind=task.kind,
        )
        messages.success(request, "Marked as canceled.")
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
        changed = form.save(user=self.request.user)
        if changed:
            audit.log(
                self.request, audit.SETTING_UPDATED,
                summary="; ".join(changed)[:300], changes=changed,
            )
            messages.success(self.request, f"Saved. {len(changed)} setting(s) changed.")
        else:
            messages.info(self.request, "Nothing changed.")
        return super().form_valid(form)
