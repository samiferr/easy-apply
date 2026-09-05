from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView

from .forms import ResumeUploadForm
from .models import ResumeImport
from .services.importer import apply_selected, build_review_sections, run_analysis


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
