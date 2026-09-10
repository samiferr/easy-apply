from django.urls import path

from . import views

app_name = "jobs"

urlpatterns = [
    path("", views.JobPostListView.as_view(), name="list"),
    path("analyze/", views.JobPostCreateView.as_view(), name="add"),
    path("<int:pk>/", views.JobPostDetailView.as_view(), name="detail"),
    path("<int:pk>/delete/", views.JobPostDeleteView.as_view(), name="delete"),
    path("<int:pk>/reanalyze/", views.JobPostReanalyzeView.as_view(), name="reanalyze"),
    path("<int:pk>/match/", views.JobPostMatchProfileView.as_view(), name="match_profile"),
    # Live state for the section rail — one call instead of 13.
    path("<int:pk>/analysis-state/", views.JobAnalysisStateView.as_view(), name="analysis_state"),
    path(
        "<int:pk>/sections/<int:section_pk>/rematch/",
        views.JobSectionRematchView.as_view(),
        name="section_rematch",
    ),
    path(
        "<int:pk>/elements/<int:element_pk>/add/",
        views.JobElementAddToProfileView.as_view(),
        name="element_add",
    ),
    path(
        "<int:pk>/elements/<int:element_pk>/rematch/",
        views.JobElementRematchView.as_view(),
        name="element_rematch",
    ),
    path(
        "<int:pk>/elements/<int:element_pk>/row/",
        views.JobElementRowView.as_view(),
        name="element_row",
    ),
]
