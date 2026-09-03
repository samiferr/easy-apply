from django.contrib import admin

from .models import JobPost, Requirement, RequirementCategory


class RequirementInline(admin.TabularInline):
    model = Requirement
    extra = 0


class RequirementCategoryInline(admin.TabularInline):
    model = RequirementCategory
    extra = 0
    show_change_link = True


@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = ["title", "company_name", "user", "status", "work_arrangement", "created_at"]
    list_filter = ["status", "work_arrangement"]
    search_fields = ["title", "company_name", "source_url", "user__email"]
    readonly_fields = ["raw_text", "created_at", "updated_at", "fetched_at", "analyzed_at"]
    inlines = [RequirementCategoryInline]


@admin.register(RequirementCategory)
class RequirementCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "category_type", "job"]
    list_filter = ["category_type"]
    inlines = [RequirementInline]
