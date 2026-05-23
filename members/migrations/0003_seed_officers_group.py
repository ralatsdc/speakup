"""Create the "Officers" auth Group, assign its permissions, and backfill
existing officers (add them to the group, set ``is_staff=True``)."""
from django.db import migrations


# Models that officers are allowed to manage. User management (members.user)
# and auth.* are intentionally excluded — those stay superuser-only.
PERMISSION_TARGETS = [
    ("meetings", "meeting"),
    ("meetings", "meetingrole"),
    ("meetings", "meetingsession"),
    ("meetings", "meetingtype"),
    ("meetings", "meetingtypeitem"),
    ("meetings", "meetingtypesession"),
    ("meetings", "attendance"),
    ("meetings", "role"),
    ("meetings", "session"),
    ("communications", "announcement"),
]
ACTIONS = ("add", "change", "delete", "view")
OFFICERS_GROUP_NAME = "Officers"


def seed_officers_group(apps, schema_editor):
    # Django's post_migrate signal creates Permission rows; in a data
    # migration we run before that signal fires, so the Permissions we want
    # to assign may not exist yet on a fresh DB. Force-create them.
    from django.contrib.auth.management import create_permissions
    from django.apps import apps as global_apps
    for app_config in global_apps.get_app_configs():
        create_permissions(app_config, verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    User = apps.get_model("members", "User")

    officers, _ = Group.objects.get_or_create(name=OFFICERS_GROUP_NAME)

    perms = []
    for app_label, model_name in PERMISSION_TARGETS:
        ct = ContentType.objects.filter(
            app_label=app_label, model=model_name
        ).first()
        if ct is None:
            continue
        for action in ACTIONS:
            perm = Permission.objects.filter(
                content_type=ct, codename=f"{action}_{model_name}"
            ).first()
            if perm is not None:
                perms.append(perm)
    officers.permissions.set(perms)

    # Backfill existing officers. The post_save signal in members/signals.py
    # does not fire on historical models inside migrations, so do the work
    # explicitly here.
    for user in User.objects.filter(is_officer=True):
        user.groups.add(officers)
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])


def unseed_officers_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=OFFICERS_GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0002_user_notes"),
        ("meetings", "0022_remove_in_person_from_role"),
        ("communications", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed_officers_group, unseed_officers_group),
    ]
