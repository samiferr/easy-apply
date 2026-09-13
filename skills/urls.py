from django.urls import path, reverse_lazy
from django.views.generic import RedirectView

from . import views
from .models import SkillCategory

app_name = "skills"

urlpatterns = [
    # Bare /skills/ is no longer a page of its own — the two kinds are two
    # screens, each with its own sidebar entry. Kept so the URL isn't a 404.
    path(
        "",
        RedirectView.as_view(
            url=reverse_lazy("skills:list", kwargs={"kind": SkillCategory.TECHNICAL})
        ),
        name="index",
    ),
    path("<int:pk>/delete/", views.SkillDeleteView.as_view(), name="delete"),
    path("<str:kind>/add/", views.SkillCreateView.as_view(), name="add"),
    path("<str:kind>/<int:pk>/edit/", views.SkillUpdateView.as_view(), name="edit"),
    path("<str:kind>/", views.SkillListView.as_view(), name="list"),
]
