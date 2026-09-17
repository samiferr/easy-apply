"""Django admin registrations.

`django.contrib.admin` stays as the raw table editor of last resort — the staff
portal at /staff/ is the screen anyone should actually be using. What is
registered here is deliberately thin, and the audit trail is read-only because
an audit trail with an edit form is not one.
"""

from django.contrib import admin

from .models import (
    Announcement,
    AuditLog,
    FeatureFlag,
    ImpersonationSession,
    Plan,
    StaffMember,
    Subscription,
    SupportNote,
    SystemSetting,
    UsageRecord,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "price_display", "interval", "is_active", "is_default"]
    list_filter = ["is_active", "is_public", "interval"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "status", "current_period_end"]
    list_filter = ["status", "plan"]
    search_fields = ["user__email", "external_customer_id"]
    autocomplete_fields = ["user", "plan"]


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ["user", "metric", "count", "period_start", "period_end"]
    list_filter = ["metric"]
    search_fields = ["user__email"]


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "state", "percentage", "updated_at"]
    list_filter = ["state"]
    filter_horizontal = ["users", "plans"]


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ["title", "level", "audience", "is_active", "starts_at", "ends_at"]
    list_filter = ["level", "audience", "is_active"]


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "created_at"]
    list_filter = ["role"]
    search_fields = ["user__email"]


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "updated_at"]


@admin.register(SupportNote)
class SupportNoteAdmin(admin.ModelAdmin):
    list_display = ["user", "author_email", "pinned", "created_at"]
    search_fields = ["user__email", "body"]


@admin.register(ImpersonationSession)
class ImpersonationSessionAdmin(admin.ModelAdmin):
    list_display = ["actor_email", "target_email", "started_at", "ended_at", "ended_reason"]
    list_filter = ["ended_reason"]
    search_fields = ["actor_email", "target_email", "reason"]
    readonly_fields = [f.name for f in ImpersonationSession._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor_email", "action", "target_repr", "while_impersonating"]
    list_filter = ["action", "while_impersonating"]
    search_fields = ["actor_email", "target_repr", "summary"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
