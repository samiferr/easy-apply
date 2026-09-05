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
]
