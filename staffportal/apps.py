from django.apps import AppConfig


class StaffPortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "staffportal"
    verbose_name = "Staff portal"

    def ready(self):
        # Registers the signal that gives every new account a subscription.
        from . import signals  # noqa: F401
