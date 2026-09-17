"""Portal routes, mounted at /staff/.

Every route here is staff-gated by `StaffPortalMixin` except
`impersonation/stop/`, which has to be reachable *from inside* a customer
session — that is the whole point of it.
"""

from django.urls import path

from .views import announcements, audit, billing, dashboard, flags, operations, team, users

app_name = "staffportal"

urlpatterns = [
    path("", dashboard.DashboardView.as_view(), name="dashboard"),
    # --- Accounts ---------------------------------------------------------
    path("users/", users.UserListView.as_view(), name="user_list"),
    path("users/export.csv", users.UserExportView.as_view(), name="user_export"),
    path("users/<int:pk>/", users.UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/suspend/", users.UserSuspendView.as_view(), name="user_suspend"),
    path("users/<int:pk>/reactivate/", users.UserReactivateView.as_view(), name="user_reactivate"),
    path(
        "users/<int:pk>/password-reset/",
        users.UserPasswordResetView.as_view(),
        name="user_password_reset",
    ),
    path("users/<int:pk>/notes/", users.UserNoteCreateView.as_view(), name="user_note_add"),
    path("users/<int:pk>/plan/", users.UserPlanChangeView.as_view(), name="user_plan_change"),
    path("users/<int:pk>/usage/reset/", users.UserUsageResetView.as_view(), name="user_usage_reset"),
    path("users/<int:pk>/export.json", users.UserDataExportView.as_view(), name="user_data_export"),
    path("users/<int:pk>/delete/", users.UserDeleteView.as_view(), name="user_delete"),
    path(
        "users/<int:pk>/impersonate/",
        users.ImpersonateStartView.as_view(),
        name="impersonate_start",
    ),
    path("impersonation/", users.ImpersonationLogView.as_view(), name="impersonation_log"),
    path("impersonation/stop/", users.ImpersonateStopView.as_view(), name="impersonate_stop"),
    # --- Billing ----------------------------------------------------------
    path("billing/", billing.BillingOverviewView.as_view(), name="billing"),
    path("billing/plans/new/", billing.PlanCreateView.as_view(), name="plan_create"),
    path("billing/plans/<int:pk>/", billing.PlanUpdateView.as_view(), name="plan_update"),
    path("billing/plans/<int:pk>/delete/", billing.PlanDeleteView.as_view(), name="plan_delete"),
    path(
        "billing/subscriptions/",
        billing.SubscriptionListView.as_view(),
        name="subscription_list",
    ),
    path(
        "billing/subscriptions/export.csv",
        billing.SubscriptionExportView.as_view(),
        name="subscription_export",
    ),
    path(
        "billing/subscriptions/<int:pk>/",
        billing.SubscriptionUpdateView.as_view(),
        name="subscription_update",
    ),
    # --- Feature flags ----------------------------------------------------
    path("flags/", flags.FlagListView.as_view(), name="flag_list"),
    path("flags/new/", flags.FlagCreateView.as_view(), name="flag_create"),
    path("flags/<int:pk>/", flags.FlagUpdateView.as_view(), name="flag_update"),
    path("flags/<int:pk>/delete/", flags.FlagDeleteView.as_view(), name="flag_delete"),
    # --- Announcements ----------------------------------------------------
    path("announcements/", announcements.AnnouncementListView.as_view(), name="announcement_list"),
    path(
        "announcements/new/",
        announcements.AnnouncementCreateView.as_view(),
        name="announcement_create",
    ),
    path(
        "announcements/<int:pk>/",
        announcements.AnnouncementUpdateView.as_view(),
        name="announcement_update",
    ),
    path(
        "announcements/<int:pk>/delete/",
        announcements.AnnouncementDeleteView.as_view(),
        name="announcement_delete",
    ),
    # --- Operations -------------------------------------------------------
    path("operations/", operations.HealthView.as_view(), name="health"),
    path("operations/queue/", operations.TaskListView.as_view(), name="task_list"),
    path("operations/queue/export.csv", operations.TaskExportView.as_view(), name="task_export"),
    path("operations/queue/<int:pk>/retry/", operations.TaskRetryView.as_view(), name="task_retry"),
    path(
        "operations/queue/<int:pk>/cancel/",
        operations.TaskCancelView.as_view(),
        name="task_cancel",
    ),
    path("operations/settings/", operations.SettingsView.as_view(), name="settings"),
    # --- Audit ------------------------------------------------------------
    path("audit/", audit.AuditListView.as_view(), name="audit_list"),
    path("audit/export.csv", audit.AuditExportView.as_view(), name="audit_export"),
    # --- Team -------------------------------------------------------------
    path("team/", team.TeamListView.as_view(), name="team_list"),
    path("team/<int:pk>/", team.TeamUpdateView.as_view(), name="team_update"),
    path("team/<int:pk>/revoke/", team.TeamRevokeView.as_view(), name="team_revoke"),
]
