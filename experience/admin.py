from django.contrib import admin

from .models import WorkExperience


@admin.register(WorkExperience)
class WorkExperienceAdmin(admin.ModelAdmin):
    list_display = ["job_title", "company", "profile", "start_date", "end_date", "is_current"]
    list_filter = ["is_current", "employment_type"]
    search_fields = ["job_title", "company", "profile__name", "profile__user__email"]
