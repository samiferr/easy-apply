from django.urls import path

from . import views

app_name = "preferences"

urlpatterns = [
    path("", views.JobPreferenceView.as_view(), name="detail"),
    path("benefits/add/", views.BenefitCreateView.as_view(), name="benefit_add"),
    path("benefits/<int:pk>/update/", views.BenefitUpdateView.as_view(), name="benefit_update"),
    path("benefits/<int:pk>/delete/", views.BenefitDeleteView.as_view(), name="benefit_delete"),
]
