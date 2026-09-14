from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.translation import gettext as _, gettext_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.mixins import ConfirmDeleteMixin

from .forms import UserLanguageForm
from .models import UserLanguage


class LanguageListView(LoginRequiredMixin, ListView):
    model = UserLanguage
    template_name = "languages/language_list.html"
    context_object_name = "user_languages"

    def get_queryset(self):
        return UserLanguage.objects.filter(profile=self.request.profile).select_related("language")


class LanguageFormMixin(LoginRequiredMixin):
    model = UserLanguage
    form_class = UserLanguageForm
    template_name = "languages/language_form.html"
    success_url = reverse_lazy("languages:list")

    def get_queryset(self):
        return UserLanguage.objects.filter(profile=self.request.profile)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["profile"] = self.request.profile
        return kwargs


class LanguageCreateView(LanguageFormMixin, CreateView):
    def form_valid(self, form):
        messages.success(self.request, f"Added {form.cleaned_data['language_name']} to your languages.")
        return super().form_valid(form)


class LanguageUpdateView(LanguageFormMixin, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Language updated.")
        return super().form_valid(form)


class LanguageDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = UserLanguage
    success_url = reverse_lazy("languages:list")
    cancel_url_name = "languages:list"
    parent_label = gettext_lazy("Languages")

    def get_queryset(self):
        return UserLanguage.objects.filter(profile=self.request.profile)

    def get_heading(self):
        return _("Delete this language?")

    def get_detail(self):
        return f"{self.object.language.name} — {self.object.get_proficiency_display()}"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        messages.info(request, f"Removed {self.object.language.name}.")
        return super().post(request, *args, **kwargs)
