from django.contrib import admin

from .models import ResumeImport


@admin.register(ResumeImport)
class ResumeImportAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "user", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["original_filename", "user__email"]
    readonly_fields = ["raw_text", "ai_response", "created_at", "analyzed_at", "applied_at"]
