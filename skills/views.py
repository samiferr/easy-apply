from itertools import groupby

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from core.mixins import ConfirmDeleteMixin

from .forms import UserSkillForm
from .models import SkillCategory, UserSkill


def _grouped_by_category(qs):
    grouped = []
    for category, items in groupby(qs, key=lambda s: s.category):
        grouped.append((category, list(items)))
    return grouped


def skills_url(kind: str) -> str:
    return reverse("skills:list", kwargs={"kind": kind})


#: Screen titles for the add/edit form, per skill kind. Lazy so the active
#: language is the request's, not whichever was current at import time.
ADD_LABELS = {
    SkillCategory.SOFT: gettext_lazy("Add a soft skill"),
    SkillCategory.TECHNICAL: gettext_lazy("Add a technical skill"),
}
EDIT_LABELS = {
    SkillCategory.SOFT: gettext_lazy("Edit soft skill"),
    SkillCategory.TECHNICAL: gettext_lazy("Edit technical skill"),
}


class SkillKindMixin:
    """Soft and technical skills are two screens, one per sidebar entry.

    The kind is a URL segment rather than a query-string tab, so each screen is
    a real, bookmarkable page and the sidebar can highlight the one you are on.
    """

    def get_kind(self):
        kind = self.kwargs.get("kind")
        if kind not in (SkillCategory.SOFT, SkillCategory.TECHNICAL):
            raise Http404("Unknown skill type")
        return kind

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["kind"] = self.get_kind()
        ctx["kind_label"] = SkillCategory.KIND_PLURALS[ctx["kind"]]
        # Whole sentences, not "Add a " + a translated noun: the article and
        # the word order differ per language.
        ctx["add_label"] = ADD_LABELS[ctx["kind"]]
        ctx["edit_label"] = EDIT_LABELS[ctx["kind"]]
        return ctx


class SkillListView(SkillKindMixin, LoginRequiredMixin, TemplateView):
    template_name = "skills/skill_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["grouped"] = _grouped_by_category(
            UserSkill.objects.filter(
                profile=self.request.profile, category__kind=ctx["kind"]
            ).select_related("category")
        )
        return ctx


class BaseSkillFormView(SkillKindMixin, LoginRequiredMixin):
    model = UserSkill
    form_class = UserSkillForm
    template_name = "skills/skill_form.html"

    def get_queryset(self):
        return UserSkill.objects.filter(profile=self.request.profile)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["kind"] = self.get_kind()
        return kwargs

    def get_success_url(self):
        return skills_url(self.get_kind())


class SkillCreateView(BaseSkillFormView, CreateView):
    def form_valid(self, form):
        form.instance.profile = self.request.profile
        messages.success(self.request, f"Added “{form.instance.name}” to your skills.")
        return super().form_valid(form)


class SkillUpdateView(BaseSkillFormView, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, f"Updated “{form.instance.name}”.")
        return super().form_valid(form)


class SkillDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = UserSkill

    def get_queryset(self):
        return UserSkill.objects.filter(profile=self.request.profile)

    def get_success_url(self):
        return skills_url(self.object.category.kind)

    def get_cancel_url(self):
        return skills_url(self.object.category.kind)

    def get_parent_label(self):
        return SkillCategory.KIND_PLURALS[self.object.category.kind]

    def get_heading(self):
        return _("Delete this skill?")

    def get_detail(self):
        return f"{self.object.name} — {self.object.get_level_display()}"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        name = self.object.name
        response = super().post(request, *args, **kwargs)
        messages.info(request, f"Removed “{name}” from your skills.")
        return response
