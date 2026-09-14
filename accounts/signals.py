from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_first_profile(sender, instance, created, **kwargs):
    """Every user starts with one workspace, so no screen is ever profile-less.

    Registration overwrites the language with the one picked on the form (see
    `RegisterView`); this default only matters for users created outside a
    request, such as by `createsuperuser`.
    """
    if not created:
        return
    from .services import bootstrap_profile

    if not Profile.objects.filter(user=instance).exists():
        bootstrap_profile(instance)
