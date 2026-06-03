"""Grant the Officers group limited user management: add / change / view on
``members.User`` — but NOT delete. Privilege fields (is_staff, is_superuser,
is_officer, groups, permissions) and hard-delete stay superuser-only, enforced
in ``CustomUserAdmin``."""
from django.db import migrations

OFFICERS_GROUP_NAME = "Officers"
USER_ACTIONS = ("add", "change", "view")  # deliberately no "delete"


def _user_perms(apps):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.filter(app_label="members", model="user").first()
    if ct is None:
        return []
    perms = []
    for action in USER_ACTIONS:
        perm = Permission.objects.filter(
            content_type=ct, codename=f"{action}_user"
        ).first()
        if perm is not None:
            perms.append(perm)
    return perms


def add_perms(apps, schema_editor):
    # Permissions may not exist yet on a fresh DB (post_migrate hasn't run).
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions
    for app_config in global_apps.get_app_configs():
        create_permissions(app_config, verbosity=0)

    Group = apps.get_model("auth", "Group")
    officers, _ = Group.objects.get_or_create(name=OFFICERS_GROUP_NAME)
    for perm in _user_perms(apps):
        officers.permissions.add(perm)


def remove_perms(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    try:
        officers = Group.objects.get(name=OFFICERS_GROUP_NAME)
    except Group.DoesNotExist:
        return
    for perm in _user_perms(apps):
        officers.permissions.remove(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0004_enforce_email_uniqueness"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(add_perms, remove_perms),
    ]
