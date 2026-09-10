from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Language switcher (set_language) — cookie-based, so no URL name changes.
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/", include("accounts.urls")),
    path("skills/", include("skills.urls")),
    path("languages/", include("languages.urls")),
    path("experience/", include("experience.urls")),
    path("education/", include("education.urls")),
    path("jobs/", include("jobs.urls")),
    path("resume/", include("resume.urls")),
    path("preferences/", include("preferences.urls")),
    path("legal/", include("legal.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
