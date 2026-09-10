from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView

from core.models import AITask
from jobs.models import JobPost

from .forms import ResumeUploadForm, TailoredResumeForm
from .models import ResumeImport, TailoredResume
from .services.importer import apply_selected, build_review_sections
from .services.pdf import render_markdown_pdf
from .tasks import enqueue_resume_analysis, enqueue_tailored_resume


class ResumeUploadView(LoginRequiredMixin, CreateView):
    model = ResumeImport
    form_class = ResumeUploadForm
    template_name = "resume/resume_upload.html"

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.original_filename = form.instance.file.name
        response = super().form_valid(form)
        # Never block the POST on an AI call — the review page shows progress.
        enqueue_resume_analysis(self.object)
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
            request,
            self.template_name,
            {
                "resume_import": resume_import,
                "sections": sections,
                "ai_task": AITask.latest_for(resume_import, AITask.RESUME_IMPORT),
            },
        )

    def post(self, request, pk):
        resume_import = self.get_object(pk, request.user)
        if resume_import.status != ResumeImport.STATUS_COMPLETED:
            return redirect("resume:review", pk=pk)

        selected_keys = set(request.POST.getlist("selected"))
        if not selected_keys:
            messages.warning(request, _("Select at least one item to add it to your profile."))
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
            messages.warning(
                request, _("Analyze this job post first, then generate a resume for it.")
            )
            return redirect(job.get_absolute_url())

        enqueue_tailored_resume(job, request.user)
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
                "ai_task": AITask.latest_for(tailored_resume, AITask.TAILORED_RESUME),
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

        if form.has_changed():
            form.instance.edited_by_user = True
        tailored_resume = form.save()

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
    def post(self, request, job_pk):
        tailored_resume = self.get_tailored_resume(job_pk)
        tailored_resume.delete()
        messages.info(request, _("Deleted the tailored resume for this job."))
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


class TailoredResumeListView(LoginRequiredMixin, ListView):
    """All tailored resumes, addressed by the jobs they were written for."""

    template_name = "resume/tailored_list.html"
    context_object_name = "tailored_resumes"
    paginate_by = 20

    def get_queryset(self):
        return TailoredResume.objects.filter(user=self.request.user).select_related("job")
