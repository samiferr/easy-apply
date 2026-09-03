from django.urls import path

from . import views

app_name = "education"

urlpatterns = [
    path("", views.EducationListView.as_view(), name="list"),
    path("degrees/add/", views.DegreeCreateView.as_view(), name="degree_add"),
    path("degrees/<int:pk>/edit/", views.DegreeUpdateView.as_view(), name="degree_edit"),
    path("degrees/<int:pk>/delete/", views.DegreeDeleteView.as_view(), name="degree_delete"),
    path("certificates/add/", views.CertificateCreateView.as_view(), name="certificate_add"),
    path(
        "certificates/<int:pk>/edit/",
        views.CertificateUpdateView.as_view(),
        name="certificate_edit",
    ),
    path(
        "certificates/<int:pk>/delete/",
        views.CertificateDeleteView.as_view(),
        name="certificate_delete",
    ),
]
