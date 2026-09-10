from django.urls import path

from . import views

app_name = "legal"

urlpatterns = [
    path("privacy/", views.PrivacyView.as_view(), name="privacy"),
    path("terms/", views.TermsView.as_view(), name="terms"),
    path("cookies/", views.CookiesView.as_view(), name="cookies"),
    path("legal-notice/", views.NoticeView.as_view(), name="notice"),
    path("contact/", views.ContactView.as_view(), name="contact"),
]
