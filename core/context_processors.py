from django.conf import settings


def site_context(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "LEGAL_ENTITY": settings.LEGAL_ENTITY,
    }
