from django.urls import path

from . import views

app_name = "skills"

urlpatterns = [
    path("", views.SkillListView.as_view(), name="list"),
    path("<str:kind>/add/", views.SkillCreateView.as_view(), name="add"),
    path("<str:kind>/<int:pk>/edit/", views.SkillUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.SkillDeleteView.as_view(), name="delete"),
]
