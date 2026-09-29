from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from core.mixins import ConfirmDeleteMixin

from . import services
from .forms import UserSkillForm
from .models import SkillCategory, UserSkill


def skills_url(kind: str, category=None) -> str:
    """The list page for a kind, optionally opening one category's tab.

    The categories are tabs over a single panel, so returning from an add,
    edit or delete without naming one would drop you on the first tab rather
    than the skill you just touched. `_skill_category_tabs.html` reads this
    fragment on load.
    """
    url = reverse("skills:list", kwargs={"kind": kind})
    return f"{url}#category-{category.pk}" if category else url


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
        if not services.is_valid_kind(kind):
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
        ctx["grouped"] = services.skills_by_category(self.request.profile, ctx["kind"])
        return ctx


class BaseSkillFormView(SkillKindMixin, LoginRequiredMixin):
    model = UserSkill
    form_class = UserSkillForm
    template_name = "skills/skill_form.html"

    def get_queryset(self):
        return services.profile_skills(self.request.profile)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["kind"] = self.get_kind()
        return kwargs

    def get_success_url(self):
        return skills_url(self.get_kind(), self.object.category)


class SkillCreateView(BaseSkillFormView, CreateView):
    def form_valid(self, form):
        self.object = services.add_skill(self.request.profile, form)
        messages.success(self.request, f"Added “{self.object.name}” to your skills.")
        return HttpResponseRedirect(self.get_success_url())


class SkillUpdateView(BaseSkillFormView, UpdateView):
    def form_valid(self, form):
        self.object = services.update_skill(form)
        messages.success(self.request, f"Updated “{self.object.name}”.")
        return HttpResponseRedirect(self.get_success_url())


class SkillDeleteView(ConfirmDeleteMixin, LoginRequiredMixin, DeleteView):
    model = UserSkill

    def get_queryset(self):
        return services.profile_skills(self.request.profile)

    def get_success_url(self):
        return skills_url(self.object.category.kind, self.object.category)

    def get_cancel_url(self):
        return skills_url(self.object.category.kind, self.object.category)

    def get_parent_label(self):
        return SkillCategory.KIND_PLURALS[self.object.category.kind]

    def get_heading(self):
        return _("Delete this skill?")

    def get_detail(self):
        return f"{self.object.name} — {self.object.get_level_display()}"

    def form_valid(self, form):
        success_url = self.get_success_url()
        services.remove_skill(self.object)
        return HttpResponseRedirect(success_url)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        name = self.object.name
        response = super().post(request, *args, **kwargs)
        messages.info(request, f"Removed “{name}” from your skills.")
        return response
