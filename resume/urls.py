from django.urls import path

from . import views

app_name = "resume"

urlpatterns = [
    path("upload/", views.ResumeUploadView.as_view(), name="upload"),
    path("tailored/", views.TailoredResumeListView.as_view(), name="tailored_list"),
    path("<int:pk>/review/", views.ResumeReviewView.as_view(), name="review"),
    # Job-tailored resumes, always addressed by the job they were written for.
    path(
        "tailored/<int:job_pk>/generate/",
        views.TailoredResumeGenerateView.as_view(),
        name="tailored_generate",
    ),
    path("tailored/<int:job_pk>/", views.TailoredResumeEditView.as_view(), name="tailored"),
    path(
        "tailored/<int:job_pk>/pdf/", views.TailoredResumePDFView.as_view(), name="tailored_pdf"
    ),
    path(
        "tailored/<int:job_pk>/markdown/",
        views.TailoredResumeMarkdownView.as_view(),
        name="tailored_markdown",
    ),
    path(
        "tailored/<int:job_pk>/delete/",
        views.TailoredResumeDeleteView.as_view(),
        name="tailored_delete",
    ),
]
