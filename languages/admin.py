from django.contrib import admin

from .models import Language, UserLanguage


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(UserLanguage)
class UserLanguageAdmin(admin.ModelAdmin):
    list_display = ["language", "profile", "proficiency"]
    list_filter = ["proficiency"]
    search_fields = ["profile__name", "profile__user__email", "language__name"]
    autocomplete_fields = ["language"]
