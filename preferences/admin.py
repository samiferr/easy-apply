from django.contrib import admin

from .models import BenefitPreference, JobPreference


class BenefitPreferenceInline(admin.TabularInline):
    model = BenefitPreference
    extra = 0


@admin.register(JobPreference)
class JobPreferenceAdmin(admin.ModelAdmin):
    list_display = ("profile", "salary_range_display", "timezone_preference", "updated_at")
    search_fields = ("profile__name", "profile__user__email")
    inlines = [BenefitPreferenceInline]
