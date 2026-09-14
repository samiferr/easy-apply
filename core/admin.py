from django.contrib import admin

from .models import AITask


@admin.register(AITask)
class AITaskAdmin(admin.ModelAdmin):
    """Read-only debugging surface for when a worker misbehaves."""

    list_display = ("id", "kind", "state", "user", "profile", "percent", "current_step", "queued_at", "finished_at")
    list_filter = ("kind", "state")
    search_fields = ("user__email", "celery_task_id", "current_step", "error_message")
    date_hierarchy = "queued_at"
    readonly_fields = [f.name for f in AITask._meta.fields] + ["percent"]

    def percent(self, obj):
        return f"{obj.percent}%"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
