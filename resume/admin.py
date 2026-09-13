from django.contrib import admin

from .models import ResumeImport, TailoredResume


@admin.register(ResumeImport)
class ResumeImportAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "profile", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["original_filename", "profile__user__email"]
    readonly_fields = ["raw_text", "ai_response", "created_at", "analyzed_at", "applied_at"]


@admin.register(TailoredResume)
class TailoredResumeAdmin(admin.ModelAdmin):
    list_display = ["job", "profile", "edited_by_user", "generated_at", "updated_at"]
    list_filter = ["edited_by_user"]
    search_fields = ["job__title", "job__company_name", "profile__user__email"]
    readonly_fields = ["created_at", "updated_at", "generated_at"]
