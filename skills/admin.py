from django.contrib import admin

from .models import SkillCategory, UserSkill


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "kind"]
    list_filter = ["kind"]
    search_fields = ["name"]


@admin.register(UserSkill)
class UserSkillAdmin(admin.ModelAdmin):
    list_display = ["name", "profile", "category", "level"]
    list_filter = ["category__kind", "category", "level"]
    search_fields = ["name", "profile__name", "profile__user__email"]
    autocomplete_fields = ["category"]
