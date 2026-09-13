from itertools import groupby

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from .forms import UserSkillForm
from .models import SkillCategory, UserSkill


def _grouped_by_category(qs):
    grouped = []
    for category, items in groupby(qs, key=lambda s: s.category):
        grouped.append((category, list(items)))
    return grouped


class SkillListView(LoginRequiredMixin, TemplateView):
    template_name = "skills/skill_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base_qs = UserSkill.objects.filter(profile=self.request.profile).select_related("category")
        ctx["soft_skills"] = _grouped_by_category(base_qs.filter(category__kind=SkillCategory.SOFT))
        ctx["technical_skills"] = _grouped_by_category(
            base_qs.filter(category__kind=SkillCategory.TECHNICAL)
        )
        ctx["active_tab"] = self.request.GET.get("tab", "soft")
        ctx["rail_tab"] = ctx["active_tab"]
        return ctx


class BaseSkillFormView(LoginRequiredMixin):
    model = UserSkill
    form_class = UserSkillForm
    template_name = "skills/skill_form.html"

    def get_kind(self):
        kind = self.kwargs.get("kind")
        if kind not in (SkillCategory.SOFT, SkillCategory.TECHNICAL):
            raise Http404("Unknown skill type")
        return kind

    def get_queryset(self):
        return UserSkill.objects.filter(profile=self.request.profile)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["kind"] = self.get_kind()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["kind"] = self.get_kind()
        ctx["kind_label"] = "Soft skill" if ctx["kind"] == SkillCategory.SOFT else "Technical skill"
        return ctx

    def get_success_url(self):
        return f"{reverse_lazy('skills:list')}?tab={self.get_kind()}"


class SkillCreateView(BaseSkillFormView, CreateView):
    def form_valid(self, form):
        form.instance.profile = self.request.profile
        messages.success(self.request, f"Added “{form.instance.name}” to your skills.")
        return super().form_valid(form)


class SkillUpdateView(BaseSkillFormView, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, f"Updated “{form.instance.name}”.")
        return super().form_valid(form)


class SkillDeleteView(LoginRequiredMixin, DeleteView):
    model = UserSkill

    def get_queryset(self):
        return UserSkill.objects.filter(profile=self.request.profile)

    def get_success_url(self):
        return f"{reverse_lazy('skills:list')}?tab={self.object.category.kind}"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        name = self.object.name
        response = super().post(request, *args, **kwargs)
        messages.info(request, f"Removed “{name}” from your skills.")
        return response

    def get(self, request, *args, **kwargs):
        # No confirmation page: deletion is triggered from a small inline form/modal.
        return redirect("skills:list")
