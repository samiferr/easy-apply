from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView

from core.ai import AIServiceError
from jobs.models import JobPost

from .forms import ResumeUploadForm, TailoredResumeForm
from .models import ResumeImport, TailoredResume
from .services.importer import apply_selected, build_review_sections, run_analysis
from .services.pdf import render_markdown_pdf
from .services.tailored import generate_tailored_resume


class ResumeUploadView(LoginRequiredMixin, CreateView):
    model = ResumeImport
    form_class = ResumeUploadForm
    template_name = "resume/resume_upload.html"

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.original_filename = form.instance.file.name
        response = super().form_valid(form)
        run_analysis(self.object)
        if self.object.status == ResumeImport.STATUS_FAILED:
            messages.error(self.request, f"Couldn't analyze your resume: {self.object.error_message}")
        return response

    def get_success_url(self):
        return reverse("resume:review", args=[self.object.pk])


class ResumeReviewView(LoginRequiredMixin, View):
    template_name = "resume/resume_review.html"

    def get_object(self, pk, user):
        return get_object_or_404(ResumeImport, pk=pk, user=user)

    def get(self, request, pk):
        resume_import = self.get_object(pk, request.user)
        sections = None
        if resume_import.status == ResumeImport.STATUS_COMPLETED:
            sections = build_review_sections(resume_import, request.user)
        return render(
            request, self.template_name, {"resume_import": resume_import, "sections": sections}
        )

    def post(self, request, pk):
        resume_import = self.get_object(pk, request.user)
        if resume_import.status != ResumeImport.STATUS_COMPLETED:
            return redirect("resume:review", pk=pk)

        selected_keys = set(request.POST.getlist("selected"))
        if not selected_keys:
            messages.warning(request, "Select at least one item to add it to your profile.")
            sections = build_review_sections(resume_import, request.user)
            return render(
                request, self.template_name, {"resume_import": resume_import, "sections": sections}
            )

        counts = apply_selected(resume_import, request.user, selected_keys)
        added = [
            f"{counts['skills']} skill(s)" if counts["skills"] else None,
            f"{counts['languages']} language(s)" if counts["languages"] else None,
            f"{counts['experience']} work experience entr{'y' if counts['experience'] == 1 else 'ies'}"
            if counts["experience"]
            else None,
            f"{counts['degrees']} degree(s)" if counts["degrees"] else None,
            f"{counts['certificates']} certificate(s)" if counts["certificates"] else None,
        ]
        added = [item for item in added if item]
        if counts["profile"]:
            added.insert(0, "your profile")
        summary = ", ".join(added) if added else "nothing new"
        messages.success(request, f"Updated {summary} from your resume.")
        return redirect("accounts:profile")


class TailoredResumeMixin(LoginRequiredMixin):
    """Shared lookup: a tailored resume is always addressed by its job."""

    def get_job(self, job_pk):
        return get_object_or_404(JobPost, pk=job_pk, user=self.request.user)

    def get_tailored_resume(self, job_pk):
        return get_object_or_404(TailoredResume, job_id=job_pk, user=self.request.user)


class TailoredResumeGenerateView(TailoredResumeMixin, View):
    """Draft (or re-draft) the resume for a job, then open the editor."""

    def post(self, request, job_pk):
        job = self.get_job(job_pk)
        if job.status != JobPost.STATUS_COMPLETED:
            messages.warning(request, "Analyze this job post first, then generate a resume for it.")
            return redirect(job.get_absolute_url())

        try:
            result = generate_tailored_resume(job, request.user)
        except AIServiceError as exc:
            messages.error(request, f"Couldn't write a resume for this job: {exc}")
            return redirect(job.get_absolute_url())

        if result.get("skipped") == "empty_profile":
            messages.warning(
                request,
                "Add your skills, experience and education to your profile first — "
                "a tailored resume is written from what you've recorded.",
            )
            return redirect(job.get_absolute_url())

        messages.success(
            request, "Drafted a tailored resume — review it, edit anything, then export it as a PDF."
        )
        return redirect("resume:tailored", job_pk=job.pk)


class TailoredResumeEditView(TailoredResumeMixin, View):
    """The Markdown editor: save changes, or save and download the PDF."""

    template_name = "resume/tailored_resume.html"

    def render_editor(self, request, tailored_resume, form):
        return render(
            request,
            self.template_name,
            {"tailored_resume": tailored_resume, "job": tailored_resume.job, "form": form},
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

        if form.has_changed():
            form.instance.edited_by_user = True
        tailored_resume = form.save()

        if request.POST.get("action") == "pdf":
            return tailored_resume_pdf_response(tailored_resume)

        messages.success(request, "Saved your changes.")
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
    def post(self, request, job_pk):
        tailored_resume = self.get_tailored_resume(job_pk)
        tailored_resume.delete()
        messages.info(request, "Deleted the tailored resume for this job.")
        return redirect("jobs:detail", pk=job_pk)


def tailored_resume_pdf_response(tailored_resume) -> HttpResponse:
    pdf_bytes = render_markdown_pdf(
        tailored_resume.markdown,
        title=tailored_resume.job.title or "Resume",
        author=tailored_resume.user.get_full_name(),
    )
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{tailored_resume.pdf_filename}"'
    return response
