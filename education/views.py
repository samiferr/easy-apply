from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.utils.translation import gettext as _, gettext_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from core.mixins import ConfirmDeleteMixin

from . import services
from .forms import CertificateForm, DegreeForm
from .models import Certificate, Degree


class EducationListView(LoginRequiredMixin, TemplateView):
    template_name = "education/education_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.education_overview(self.request.profile))
        return ctx


class DegreeFormMixin(LoginRequiredMixin):
    model = Degree
    form_class = DegreeForm
    template_name = "education/degree_form.html"
    success_url = reverse_lazy("education:list")

    def get_queryset(self):
        return services.profile_degrees(self.request.profile)


class DegreeCreateView(DegreeFormMixin, CreateView):
    def form_valid(self, form):
        self.object = services.add_degree(self.request.profile, form)
        messages.success(self.request, f"Added your degree from {self.object.school}.")
        return HttpResponseRedirect(self.get_success_url())


class DegreeUpdateView(DegreeFormMixin, UpdateView):
    def form_valid(self, form):
        self.object = services.update_degree(form)
        messages.success(self.request, "Degree updated.")
        return HttpResponseRedirect(self.get_success_url())


class DegreeDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = Degree
    success_url = reverse_lazy("education:list")
    cancel_url_name = "education:list"
    parent_label = gettext_lazy("Education")

    def get_queryset(self):
        return services.profile_degrees(self.request.profile)

    def get_heading(self):
        return _("Delete this degree?")

    def get_detail(self):
        return f"{self.object.degree} — {self.object.school}"

    def form_valid(self, form):
        success_url = self.get_success_url()
        services.remove_degree(self.object)
        return HttpResponseRedirect(success_url)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed {self.object.degree} — {self.object.school}.")
        return super().post(request, *args, **kwargs)


class CertificateFormMixin(LoginRequiredMixin):
    model = Certificate
    form_class = CertificateForm
    template_name = "education/certificate_form.html"
    success_url = reverse_lazy("education:list")

    def get_queryset(self):
        return services.profile_certificates(self.request.profile)


class CertificateCreateView(CertificateFormMixin, CreateView):
    def form_valid(self, form):
        self.object = services.add_certificate(self.request.profile, form)
        messages.success(self.request, f"Added the “{self.object.name}” certificate.")
        return HttpResponseRedirect(self.get_success_url())


class CertificateUpdateView(CertificateFormMixin, UpdateView):
    def form_valid(self, form):
        self.object = services.update_certificate(form)
        messages.success(self.request, "Certificate updated.")
        return HttpResponseRedirect(self.get_success_url())


class CertificateDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = Certificate
    success_url = reverse_lazy("education:list")
    cancel_url_name = "education:list"
    parent_label = gettext_lazy("Education")

    def get_queryset(self):
        return services.profile_certificates(self.request.profile)

    def get_heading(self):
        return _("Delete this certificate?")

    def get_detail(self):
        return f"{self.object.name} — {self.object.issuing_organization}"

    def form_valid(self, form):
        success_url = self.get_success_url()
        services.remove_certificate(self.object)
        return HttpResponseRedirect(success_url)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed the “{self.object.name}” certificate.")
        return super().post(request, *args, **kwargs)
