from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("recap/preview/", views.ExportPreviewView.as_view(), name="export_preview"),
    path("recap/download/", views.ExportMarkdownView.as_view(), name="export_markdown"),
]
