from django.contrib import admin

from .models import JobElement, JobPost, JobSection


class JobElementInline(admin.TabularInline):
    model = JobElement
    extra = 0
    fields = ["order", "text", "match_status", "match_evidence", "added_to_profile_at"]


class JobSectionInline(admin.TabularInline):
    model = JobSection
    extra = 0
    fields = ["order", "key", "match_state", "matched_at"]
    readonly_fields = ["order"]
    show_change_link = True


@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = ["title", "company_name", "user", "status", "work_arrangement", "created_at"]
    list_filter = ["status", "work_arrangement"]
    search_fields = ["title", "company_name", "source_url", "user__email"]
    readonly_fields = ["raw_text", "created_at", "updated_at", "fetched_at", "analyzed_at"]
    inlines = [JobSectionInline]


@admin.register(JobSection)
class JobSectionAdmin(admin.ModelAdmin):
    list_display = ["key", "job", "match_state", "matched_at"]
    list_filter = ["key", "match_state"]
    inlines = [JobElementInline]
