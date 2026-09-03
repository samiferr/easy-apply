from django.contrib import admin

from .models import Certificate, Degree


@admin.register(Degree)
class DegreeAdmin(admin.ModelAdmin):
    list_display = ["degree", "school", "user", "start_date", "end_date"]
    search_fields = ["degree", "school", "user__email"]


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ["name", "issuing_organization", "user", "issue_date", "expiry_date"]
    search_fields = ["name", "issuing_organization", "user__email"]
