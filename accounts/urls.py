from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.EmailLoginView.as_view(), name="login"),
    path("logout/", views.logout_confirm_view, name="logout_confirm"),
    path("logout/confirm/", LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("security/", views.SecurityView.as_view(), name="security"),
    # Profiles (workspaces)
    path("profiles/", views.ProfileListView.as_view(), name="profile_list"),
    path("profiles/new/", views.ProfileCreateView.as_view(), name="profile_create"),
    path("profiles/<int:pk>/rename/", views.ProfileRenameView.as_view(), name="profile_rename"),
    path("profiles/<int:pk>/switch/", views.ProfileSwitchView.as_view(), name="profile_switch"),
    path("profiles/<int:pk>/delete/", views.ProfileDeleteView.as_view(), name="profile_delete"),
    # Password reset / recovery
    path(
        "password-reset/",
        views.EasyApplyPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        views.EasyApplyPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.EasyApplyPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        views.EasyApplyPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
