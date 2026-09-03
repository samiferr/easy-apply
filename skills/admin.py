from django.contrib import admin

from .models import SkillCategory, UserSkill


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "kind"]
    list_filter = ["kind"]
    search_fields = ["name"]


@admin.register(UserSkill)
class UserSkillAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "category", "level"]
    list_filter = ["category__kind", "category", "level"]
    search_fields = ["name", "user__email"]
    autocomplete_fields = ["category"]
