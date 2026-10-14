"""Grant the Officers group add / change / delete / view on ``Sender`` so
officers can add and retire the addresses they choose from on the
review-before-send page, without needing a superuser."""
from django.db import migrations

OFFICERS_GROUP_NAME = "Officers"
ACTIONS = ("add", "change", "delete", "view")


def _sender_perms(apps):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.filter(app_label="communications", model="sender").first()
    if ct is None:
        return []
    return list(Permission.objects.filter(
        content_type=ct, codename__in=[f"{a}_sender" for a in ACTIONS]))


def add_perms(apps, schema_editor):
    # Permissions don't exist yet on a fresh DB (post_migrate hasn't run).
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions
    for app_config in global_apps.get_app_configs():
        create_permissions(app_config, verbosity=0)

    Group = apps.get_model("auth", "Group")
    officers, _ = Group.objects.get_or_create(name=OFFICERS_GROUP_NAME)
    officers.permissions.add(*_sender_perms(apps))


def remove_perms(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    try:
        officers = Group.objects.get(name=OFFICERS_GROUP_NAME)
    except Group.DoesNotExist:
        return
    officers.permissions.remove(*_sender_perms(apps))


class Migration(migrations.Migration):

    dependencies = [
        ("communications", "0004_sender"),
        ("members", "0005_officers_manage_users"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(add_perms, remove_perms),
    ]
