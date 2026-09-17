"""Give every new account a subscription the moment it exists.

Provisioning at registration rather than lazily on first use means no code path
anywhere has to cope with a user that has no plan, and the portal's subscriber
count matches the account count on day one.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="staffportal.provision")
def provision_subscription(sender, instance, created, raw=False, **kwargs):
    # `raw` is a fixture load: the database is mid-restore and nothing else
    # should be written into it.
    if not created or raw:
        return
    from .services.subscriptions import ensure_subscription

    ensure_subscription(instance)
