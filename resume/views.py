from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView

from core.exceptions import Blocked, PreconditionFailed
from jobs.services import profile_jobs

from . import services
from .forms import ResumeUploadForm, TailoredResumeForm
from .models import ResumeImport


class ResumeUploadView(LoginRequiredMixin, CreateView):
    model = ResumeImport
    form_class = ResumeUploadForm
    template_name = "resume/resume_upload.html"

    def form_valid(self, form):
        try:
            self.object = services.start_resume_import(
                self.request.user, self.request.profile, form
            )
        except Blocked as blocked:
            messages.error(self.request, str(blocked))
            return self.form_invalid(form)
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("resume:review", args=[self.object.pk])


class ResumeReviewView(LoginRequiredMixin, View):
    template_name = "resume/resume_review.html"

    def get_object(self, pk, profile):
        return get_object_or_404(services.profile_imports(profile), pk=pk)

    def get(self, request, pk):
        resume_import = self.get_object(pk, request.profile)
        return render(
            request,
            self.template_name,
            {
                "resume_import": resume_import,
                "sections": services.review_checklist(resume_import, request.profile),
                "ai_task": services.import_task(resume_import),
            },
        )

    def post(self, request, pk):
        resume_import = self.get_object(pk, request.profile)
        if not services.is_reviewable(resume_import):
            return redirect("resume:review", pk=pk)

        try:
            summary = services.apply_review(
                resume_import, request.profile, set(request.POST.getlist("selected"))
            )
        except PreconditionFailed as error:
            messages.warning(request, str(error))
            sections = services.build_review_sections(resume_import, request.profile)
            return render(
                request, self.template_name, {"resume_import": resume_import, "sections": sections}
            )

        messages.success(request, summary)
        return redirect("accounts:profile")


class TailoredResumeMixin(LoginRequiredMixin):
    """Shared lookup: a tailored resume is always addressed by its job."""

    def get_job(self, job_pk):
        return get_object_or_404(profile_jobs(self.request.profile), pk=job_pk)

    def get_tailored_resume(self, job_pk):
        return get_object_or_404(
            services.profile_tailored_resumes(self.request.profile), job_id=job_pk
        )


class TailoredResumeGenerateView(TailoredResumeMixin, View):
    """Draft (or re-draft) the resume for a job, then open the editor."""

    def post(self, request, job_pk):
        job = self.get_job(job_pk)
        try:
            services.start_tailored_resume(request.user, job)
        except PreconditionFailed as error:
            messages.warning(request, str(error))
            return redirect(job.get_absolute_url())
        except Blocked as blocked:
            messages.error(request, str(blocked))
            return redirect(job.get_absolute_url())

        messages.info(request, _("Writing your tailored resume — this takes a moment."))
        return redirect("resume:tailored", job_pk=job.pk)


class TailoredResumeEditView(TailoredResumeMixin, View):
    """The Markdown editor: save changes, or save and download the PDF."""

    template_name = "resume/tailored_resume.html"

    def render_editor(self, request, tailored_resume, form):
        return render(
            request,
            self.template_name,
            {
                "tailored_resume": tailored_resume,
                "job": tailored_resume.job,
                "form": form,
                "ai_task": services.tailored_resume_task(tailored_resume),
            },
        )

    def get(self, request, job_pk):
        tailored_resume = self.get_tailored_resume(job_pk)
        form = TailoredResumeForm(instance=tailored_resume)
        return self.render_editor(request, tailored_resume, form)

    def post(self, request, job_pk):
        tailored_resume = self.get_tailored_resume(job_pk)
        form = TailoredResumeForm(request.POST, instance=tailored_resume)
        if not form.is_valid():
            return self.render_editor(request, tailored_resume, form)

        tailored_resume = services.save_tailored_edits(form)

        if request.POST.get("action") == "pdf":
            return tailored_resume_pdf_response(tailored_resume)

        messages.success(request, _("Saved your changes."))
        return redirect("resume:tailored", job_pk=job_pk)


class TailoredResumePDFView(TailoredResumeMixin, View):
    """Download the saved resume as a PDF."""

    def get(self, request, job_pk):
        return tailored_resume_pdf_response(self.get_tailored_resume(job_pk))


class TailoredResumeMarkdownView(TailoredResumeMixin, View):
    """Download the saved resume as a .md file."""

    def get(self, request, job_pk):
        tailored_resume = self.get_tailored_resume(job_pk)
        response = HttpResponse(
            tailored_resume.markdown, content_type="text/markdown; charset=utf-8"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{tailored_resume.markdown_filename}"'
        )
        return response


class TailoredResumeDeleteView(TailoredResumeMixin, View):
    def get(self, request, job_pk):
        tailored_resume = self.get_tailored_resume(job_pk)
        return render(
            request,
            "core/confirm_delete.html",
            {
                "page_title": _("Delete this tailored resume?"),
                "heading": _("Delete this tailored resume?"),
                "detail": tailored_resume.job.title or _("Untitled role"),
                "cancel_url": reverse("resume:tailored", args=[job_pk]),
                "parent_crumbs": [
                    {"label": _("Tailored resumes"), "url": reverse("resume:tailored_list")},
                    {
                        "label": tailored_resume.job.title or _("Untitled role"),
                        "url": reverse("resume:tailored", args=[job_pk]),
                    },
                ],
            },
        )

    def post(self, request, job_pk):
        services.remove_tailored_resume(self.get_tailored_resume(job_pk))
        messages.info(request, _("Deleted the tailored resume for this job."))
        return redirect("jobs:detail", pk=job_pk)


def tailored_resume_pdf_response(tailored_resume) -> HttpResponse:
    response = HttpResponse(
        services.tailored_resume_pdf(tailored_resume), content_type="application/pdf"
    )
    response["Content-Disposition"] = f'attachment; filename="{tailored_resume.pdf_filename}"'
    return response


class TailoredResumeListView(LoginRequiredMixin, ListView):
    """All tailored resumes, addressed by the jobs they were written for."""

    template_name = "resume/tailored_list.html"
    context_object_name = "tailored_resumes"
    paginate_by = 20

    def get_queryset(self):
        return services.list_tailored_resumes(self.request.profile)
