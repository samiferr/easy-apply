from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from .forms import CertificateForm, DegreeForm
from .models import Certificate, Degree


class EducationListView(LoginRequiredMixin, TemplateView):
    # Tells the shared profile rail which tab is active.
    extra_context = {"active_tab": "education"}
    template_name = "education/education_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["degrees"] = Degree.objects.filter(profile=self.request.profile)
        ctx["certificates"] = Certificate.objects.filter(profile=self.request.profile)
        return ctx


class DegreeFormMixin(LoginRequiredMixin):
    model = Degree
    form_class = DegreeForm
    template_name = "education/degree_form.html"
    success_url = reverse_lazy("education:list")

    def get_queryset(self):
        return Degree.objects.filter(profile=self.request.profile)


class DegreeCreateView(DegreeFormMixin, CreateView):
    def form_valid(self, form):
        form.instance.profile = self.request.profile
        messages.success(self.request, f"Added your degree from {form.instance.school}.")
        return super().form_valid(form)


class DegreeUpdateView(DegreeFormMixin, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Degree updated.")
        return super().form_valid(form)


class DegreeDeleteView(LoginRequiredMixin, DeleteView):
    model = Degree
    success_url = reverse_lazy("education:list")

    def get_queryset(self):
        return Degree.objects.filter(profile=self.request.profile)

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
        return Certificate.objects.filter(profile=self.request.profile)


class CertificateCreateView(CertificateFormMixin, CreateView):
    def form_valid(self, form):
        form.instance.profile = self.request.profile
        messages.success(self.request, f"Added the “{form.instance.name}” certificate.")
        return super().form_valid(form)


class CertificateUpdateView(CertificateFormMixin, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Certificate updated.")
        return super().form_valid(form)


class CertificateDeleteView(LoginRequiredMixin, DeleteView):
    model = Certificate
    success_url = reverse_lazy("education:list")

    def get_queryset(self):
        return Certificate.objects.filter(profile=self.request.profile)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed the “{self.object.name}” certificate.")
        return super().post(request, *args, **kwargs)
