from django.urls import path

from . import views

app_name = "resume"

urlpatterns = [
    path("upload/", views.ResumeUploadView.as_view(), name="upload"),
    path("<int:pk>/review/", views.ResumeReviewView.as_view(), name="review"),
]
