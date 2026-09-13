from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, View

from core.models import AITask
from resume.models import TailoredResume

from .forms import JobAnalysisForm
from .models import JobElement, JobPost, JobSection
from .profile_targets import get_add_target
from .sections import SECTIONS
from .tasks import (
    enqueue_element_match,
    enqueue_full_match,
    enqueue_job_analysis,
    enqueue_section_match,
)


class JobPostListView(LoginRequiredMixin, ListView):
    model = JobPost
    template_name = "jobs/job_list.html"
    context_object_name = "job_posts"
    paginate_by = 20

    def get_queryset(self):
        qs = JobPost.objects.filter(profile=self.request.profile).prefetch_related(
            "sections__elements"
        )
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(title__icontains=query)
                | Q(company_name__icontains=query)
                | Q(location__icontains=query)
                | Q(source_url__icontains=query)
            )
        status = self.request.GET.get("status", "").strip()
        if status in dict(JobPost.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status"] = self.request.GET.get("status", "")
        ctx["status_choices"] = JobPost.STATUS_CHOICES
        ctx["total_count"] = JobPost.objects.filter(profile=self.request.profile).count()
        return ctx


class JobPostCreateView(LoginRequiredMixin, CreateView):
    """Enqueue the analysis and redirect straight to the detail page.

    The POST never blocks on an AI call — the detail page shows live progress.
    """

    model = JobPost
    form_class = JobAnalysisForm
    template_name = "jobs/job_form.html"

    def form_valid(self, form):
        form.instance.profile = self.request.profile
        response = super().form_valid(form)
        # The profile's language, not the browser's: a job analyzed in a French
        # workspace stays French even if the UI is being read in English.
        enqueue_job_analysis(self.object)
        messages.info(
            self.request,
            _("Analyzing this job post — the sections will fill in as they finish."),
        )
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class JobPostDetailView(LoginRequiredMixin, DetailView):
    model = JobPost
    template_name = "jobs/job_detail.html"
    context_object_name = "job"

    def get_queryset(self):
        return JobPost.objects.filter(profile=self.request.profile).prefetch_related(
            "sections__elements"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = self.object
        by_key = {s.key: s for s in job.sections.all()}
        # Always render the rail in the canonical order, including sections the
        # posting had nothing for — they show as empty rather than disappearing.
        ctx["rail"] = [
            {"spec": spec, "section": by_key.get(spec.key)} for spec in SECTIONS
        ]
        ctx["match_summary"] = job.element_match_summary()
        ctx["tailored_resume"] = TailoredResume.objects.filter(job=job).first()
        ctx["ai_task"] = AITask.latest_for(job, AITask.JOB_ANALYSIS)
        ctx["match_task"] = AITask.latest_for(job, AITask.JOB_MATCH)
        return ctx


class JobPostDeleteView(LoginRequiredMixin, DeleteView):
    model = JobPost
    success_url = reverse_lazy("jobs:list")

    def get_queryset(self):
        return JobPost.objects.filter(profile=self.request.profile)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(
            request,
            _("Deleted “%(title)s”.") % {"title": self.object.title or self.object.source_url},
        )
        return super().post(request, *args, **kwargs)


class JobPostReanalyzeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        job = get_object_or_404(JobPost, pk=pk, profile=request.profile)
        enqueue_job_analysis(job)
        messages.info(request, _("Re-analyzing this job post."))
        return redirect(job.get_absolute_url())


class JobPostMatchProfileView(LoginRequiredMixin, View):
    """Re-run matching across every section of an already-extracted job."""

    def post(self, request, pk):
        job = get_object_or_404(JobPost, pk=pk, profile=request.profile)
        if not job.sections.exists():
            messages.warning(
                request, _("Analyze this job post first, then match it to your profile.")
            )
            return redirect(job.get_absolute_url())
        enqueue_full_match(job)
        messages.info(request, _("Matching this job against your profile."))
        return redirect(job.get_absolute_url())


class JobSectionRematchView(LoginRequiredMixin, View):
    """Retry one section — the per-tab Retry button."""

    def post(self, request, pk, section_pk):
        section = get_object_or_404(
            JobSection, pk=section_pk, job__pk=pk, job__profile=request.profile
        )
        enqueue_section_match(section)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            section.refresh_from_db()
            return JsonResponse(
                {
                    "ok": True,
                    "section_html": _render_section(request, section),
                    "state": section.match_state,
                }
            )
        messages.info(
            request, _("Re-matching %(section)s.") % {"section": str(section.label)}
        )
        return redirect(f"{section.job.get_absolute_url()}#{section.key}")


def _render_section(request, section):
    return render_to_string(
        "jobs/_section_panel.html",
        {"section": section, "spec": section.spec, "job": section.job},
        request=request,
    )


class JobAnalysisStateView(LoginRequiredMixin, View):
    """One call returning every section's state, so the rail updates without
    13 separate requests (spec §7.5)."""

    def get(self, request, pk):
        job = get_object_or_404(
            JobPost.objects.prefetch_related("sections__elements"), pk=pk, profile=request.profile
        )
        task = AITask.latest_for(job, AITask.JOB_ANALYSIS)
        match_task = AITask.latest_for(job, AITask.JOB_MATCH)
        live = [t for t in (task, match_task) if t and not t.is_terminal]
        sections = []
        for section in job.sections.all():
            summary = section.match_summary()
            sections.append(
                {
                    "key": section.key,
                    "id": section.pk,
                    "state": section.match_state,
                    "error": section.match_error,
                    "total": summary["total"],
                    "strong": summary["strong"],
                    "partial": summary["partial"],
                    "none": summary["none"],
                    "analyzed": summary["analyzed"],
                }
            )
        return JsonResponse(
            {
                "job_status": job.status,
                "sections": sections,
                "summary": job.element_match_summary(),
                "is_running": bool(live) or job.status in (JobPost.STATUS_PENDING, JobPost.STATUS_PROCESSING),
                "task_id": live[0].pk if live else None,
            }
        )


# ---------------------------------------------------------------------------
# Per-element: "Add to my profile" and single-element re-evaluation
# ---------------------------------------------------------------------------
class JobElementAddToProfileView(LoginRequiredMixin, View):
    """GET renders the modal form fragment; POST creates the profile object and
    enqueues a re-evaluation of that one element (spec §4)."""

    def get_element(self, request, pk, element_pk):
        return get_object_or_404(
            JobElement.objects.select_related("section", "section__job"),
            pk=element_pk,
            section__job__pk=pk,
            section__job__profile=request.profile,
        )

    def _modal_html(self, request, element, target, form):
        return render_to_string(
            "jobs/_add_to_profile_modal.html",
            {"element": element, "target": target, "form": form, "section": element.section},
            request=request,
        )

    def get(self, request, pk, element_pk):
        element = self.get_element(request, pk, element_pk)
        target = get_add_target(element.section.key)
        if target is None:
            return JsonResponse(
                {"ok": False, "error": _("This section can't be added to your profile.")},
                status=400,
            )
        form = target.form_class(
            profile=request.profile, element=element, initial=target.initial_for(element)
        )
        return JsonResponse(
            {"ok": True, "modal_html": self._modal_html(request, element, target, form)}
        )

    def post(self, request, pk, element_pk):
        element = self.get_element(request, pk, element_pk)
        target = get_add_target(element.section.key)
        if target is None:
            return JsonResponse(
                {"ok": False, "error": _("This section can't be added to your profile.")},
                status=400,
            )

        form = target.form_class(request.POST, profile=request.profile, element=element)
        if not form.is_valid():
            # Duplicates and conflicts come back in the modal, never as a 500.
            return JsonResponse(
                {"ok": False, "modal_html": self._modal_html(request, element, target, form)},
                status=422,
            )

        form.save()
        element.added_to_profile_at = timezone.now()
        element.save(update_fields=["added_to_profile_at"])

        task = enqueue_element_match(element)
        element.refresh_from_db()
        return JsonResponse(
            {
                "ok": True,
                "task_id": task.pk,
                "row_html": _render_element_row(request, element),
                "element_id": element.pk,
            }
        )


class JobElementRematchView(LoginRequiredMixin, View):
    """Re-evaluate one element on demand, without adding anything."""

    def post(self, request, pk, element_pk):
        element = get_object_or_404(
            JobElement.objects.select_related("section", "section__job"),
            pk=element_pk,
            section__job__pk=pk,
            section__job__profile=request.profile,
        )
        task = enqueue_element_match(element)
        element.refresh_from_db()
        return JsonResponse(
            {
                "ok": True,
                "task_id": task.pk,
                "row_html": _render_element_row(request, element),
                "element_id": element.pk,
            }
        )


class JobElementRowView(LoginRequiredMixin, View):
    """The finished row, fetched once a re-evaluation task reaches a terminal state."""

    def get(self, request, pk, element_pk):
        element = get_object_or_404(
            JobElement.objects.select_related("section", "section__job"),
            pk=element_pk,
            section__job__pk=pk,
            section__job__profile=request.profile,
        )
        job = element.section.job
        return JsonResponse(
            {
                "ok": True,
                "element_id": element.pk,
                "row_html": _render_element_row(request, element),
                "section_summary": element.section.match_summary(),
                "summary": job.element_match_summary(),
            }
        )


def _render_element_row(request, element):
    return render_to_string(
        "jobs/_element_row.html",
        {
            "element": element,
            "section": element.section,
            "job": element.section.job,
            "can_add": bool(get_add_target(element.section.key)),
        },
        request=request,
    )
