from core.forms import StyledModelForm

from .models import SkillCategory, UserSkill


class UserSkillForm(StyledModelForm):
    class Meta:
        model = UserSkill
        fields = ["category", "name", "level"]
        labels = {"name": "Skill name"}

    def __init__(self, *args, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        if kind:
            self.fields["category"].queryset = SkillCategory.objects.filter(kind=kind)
        self.fields["name"].widget.attrs["placeholder"] = (
            "e.g. Public speaking" if kind == SkillCategory.SOFT else "e.g. Python"
        )

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        if self.kind and category and category.kind != self.kind:
            self.add_error("category", "Please choose a category that matches this skill type.")
        return cleaned
