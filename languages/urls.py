from django.urls import path

from . import views

app_name = "languages"

urlpatterns = [
    path("", views.LanguageListView.as_view(), name="list"),
    path("add/", views.LanguageCreateView.as_view(), name="add"),
    path("<int:pk>/edit/", views.LanguageUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.LanguageDeleteView.as_view(), name="delete"),
]
