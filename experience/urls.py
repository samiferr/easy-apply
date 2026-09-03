from django.urls import path

from . import views

app_name = "experience"

urlpatterns = [
    path("", views.ExperienceListView.as_view(), name="list"),
    path("add/", views.ExperienceCreateView.as_view(), name="add"),
    path("<int:pk>/edit/", views.ExperienceUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.ExperienceDeleteView.as_view(), name="delete"),
]
