from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.translation import gettext as _, gettext_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, View

from core.exceptions import Blocked, PreconditionFailed, Refused
from core.mixins import ConfirmDeleteMixin

from . import services
from .forms import JobAnalysisForm
from .models import JobPost


class JobPostListView(LoginRequiredMixin, ListView):
    model = JobPost
    template_name = "jobs/job_list.html"
    context_object_name = "job_posts"
    paginate_by = 20

    def get_queryset(self):
        return services.search_jobs(
            self.request.profile,
            self.request.GET.get("q", ""),
            self.request.GET.get("status", ""),
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["status"] = self.request.GET.get("status", "")
        ctx["status_choices"] = JobPost.STATUS_CHOICES
        ctx["total_count"] = services.profile_jobs(self.request.profile).count()
        return ctx


class JobPostCreateView(LoginRequiredMixin, CreateView):
    """Enqueue the analysis and redirect straight to the detail page.

    The POST never blocks on an AI call — the detail page shows live progress.
    """

    model = JobPost
    form_class = JobAnalysisForm
    template_name = "jobs/job_form.html"

    def form_valid(self, form):
        try:
            self.object = services.start_job_analysis(
                self.request.user, self.request.profile, form
            )
        except Blocked as blocked:
            # `form_invalid` keeps the pasted posting on screen rather than
            # throwing it away.
            messages.error(self.request, str(blocked))
            return self.form_invalid(form)
        messages.info(
            self.request,
            _("Analyzing this job post — the sections will fill in as they finish."),
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return self.object.get_absolute_url()


class JobPostDetailView(LoginRequiredMixin, DetailView):
    model = JobPost
    template_name = "jobs/job_detail.html"
    context_object_name = "job"

    def get_queryset(self):
        return services.profile_jobs_with_sections(self.request.profile)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.job_detail_context(self.object))
        return ctx


class JobPostDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = JobPost
    success_url = reverse_lazy("jobs:list")
    cancel_url_name = "jobs:list"
    parent_label = gettext_lazy("Job posts")

    def get_queryset(self):
        return services.profile_jobs(self.request.profile)

    def get_heading(self):
        return _("Delete this job post analysis?")

    def get_detail(self):
        return self.object.title or _("Untitled role")

    def get_warning(self):
        if services.has_tailored_resume(self.object):
            return _("This also deletes the tailored resume written for it. This can't be undone.")
        return _("This can't be undone.")

    def form_valid(self, form):
        success_url = self.get_success_url()
        services.remove_job(self.object)
        return HttpResponseRedirect(success_url)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(
            request,
            _("Deleted “%(title)s”.") % {"title": self.object.title or _("Untitled role")},
        )
        return super().post(request, *args, **kwargs)


class JobPostReanalyzeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        job = get_object_or_404(services.profile_jobs(request.profile), pk=pk)
        try:
            services.reanalyze_job(request.user, job)
        except Blocked as blocked:
            messages.error(request, str(blocked))
        else:
            messages.info(request, _("Re-analyzing this job post."))
        return redirect(job.get_absolute_url())


class JobPostMatchProfileView(LoginRequiredMixin, View):
    """Re-run matching across every section of an already-extracted job."""

    def post(self, request, pk):
        job = get_object_or_404(services.profile_jobs(request.profile), pk=pk)
        try:
            services.rematch_job(job)
        except PreconditionFailed as error:
            messages.warning(request, str(error))
        except Blocked as blocked:
            messages.error(request, str(blocked))
        else:
            messages.info(request, _("Matching this job against your profile."))
        return redirect(job.get_absolute_url())


class JobSectionRematchView(LoginRequiredMixin, View):
    """Retry one section — the per-tab Retry button."""

    def post(self, request, pk, section_pk):
        section = get_object_or_404(
            services.profile_sections(request.profile), pk=section_pk, job__pk=pk
        )
        services.rematch_section(section)
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
        job = get_object_or_404(services.profile_jobs_with_sections(request.profile), pk=pk)
        return JsonResponse(services.analysis_state(job))


# ---------------------------------------------------------------------------
# Per-element: "Add to my profile" and single-element re-evaluation
# ---------------------------------------------------------------------------
def _get_element(request, pk, element_pk):
    return get_object_or_404(
        services.profile_elements(request.profile), pk=element_pk, section__job__pk=pk
    )


class JobElementAddToProfileView(LoginRequiredMixin, View):
    """GET renders the modal form fragment; POST creates the profile object and
    enqueues a re-evaluation of that one element (spec §4)."""

    def _modal_html(self, request, element, target, form):
        return render_to_string(
            "jobs/_add_to_profile_modal.html",
            {"element": element, "target": target, "form": form, "section": element.section},
            request=request,
        )

    def get(self, request, pk, element_pk):
        element = _get_element(request, pk, element_pk)
        try:
            target = services.add_target_for(element)
        except Refused as refused:
            return JsonResponse({"ok": False, "error": str(refused)}, status=400)
        form = services.add_to_profile_form(request.profile, element, target)
        return JsonResponse(
            {"ok": True, "modal_html": self._modal_html(request, element, target, form)}
        )

    def post(self, request, pk, element_pk):
        element = _get_element(request, pk, element_pk)
        try:
            target = services.add_target_for(element)
        except Refused as refused:
            return JsonResponse({"ok": False, "error": str(refused)}, status=400)

        form = services.add_to_profile_form(request.profile, element, target, request.POST)
        if not form.is_valid():
            # Duplicates and conflicts come back in the modal, never as a 500.
            return JsonResponse(
                {"ok": False, "modal_html": self._modal_html(request, element, target, form)},
                status=422,
            )

        task = services.add_to_profile(element, form)
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
        element = _get_element(request, pk, element_pk)
        task = services.rematch_element(element)
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
        element = _get_element(request, pk, element_pk)
        return JsonResponse(
            {
                "ok": True,
                "element_id": element.pk,
                "row_html": _render_element_row(request, element),
                **services.element_row_state(element),
            }
        )


def _render_element_row(request, element):
    return render_to_string(
        "jobs/_element_row.html",
        {
            "element": element,
            "section": element.section,
            "job": element.section.job,
            "can_add": services.can_add_to_profile(element),
        },
        request=request,
    )
