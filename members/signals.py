"""Sync ``is_officer`` to Django's ``is_staff`` and ``Officers`` group membership.

``is_officer`` is the single source of truth for "club officer" status. This
post_save handler keeps two derived facts in lockstep:

- ``is_staff`` is set whenever ``is_officer`` is true (so the user can log into
  the Django admin), and cleared when ``is_officer`` is false — except for
  superusers, who always retain ``is_staff``.
- The user is added to / removed from the "Officers" group, which carries the
  meeting and communications permissions seeded by ``members`` migration 0003.

The bulk admin actions in ``members/admin.py`` were rewritten to iterate and
call ``.save()`` per row so this signal fires for them; plain
``queryset.update()`` would bypass it.
"""
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User

OFFICERS_GROUP_NAME = "Officers"


@receiver(post_save, sender=User)
def sync_officer_membership(sender, instance, **kwargs):
    """Keep ``is_staff`` and Officers-group membership aligned with ``is_officer``."""
    officers_group, _ = Group.objects.get_or_create(name=OFFICERS_GROUP_NAME)

    if instance.is_officer:
        if not instance.is_staff:
            # Bypass save() to avoid re-triggering this signal.
            User.objects.filter(pk=instance.pk).update(is_staff=True)
            instance.is_staff = True
        instance.groups.add(officers_group)
    else:
        # Superusers always need is_staff; don't strip it from them.
        if instance.is_staff and not instance.is_superuser:
            User.objects.filter(pk=instance.pk).update(is_staff=False)
            instance.is_staff = False
        instance.groups.remove(officers_group)
