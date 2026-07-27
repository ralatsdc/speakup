# Data migration: add a "Co-Timer" role.

from django.db import migrations

# Fields copied from Timer so the two timing roles behave identically. The
# name is the only thing that differs — Co-Timer is a peer timer, not tied to
# onsite/online. guidance_document is intentionally not cloned.
CLONED_FIELDS = [
    "points",
    "min_minutes",
    "max_minutes",
    "shows_pathways_fields",
    "is_evaluator_role",
    "is_evaluated_role",
    "show_on_agenda",
    "single_holder_all_slots",
]

CO_TIMER = "Co-Timer"
TIMER = "Timer"
MEETING_TYPE = "Regular Meeting"
SESSION = "Intro & Warm-up"


def add_co_timer(apps, schema_editor):
    Role = apps.get_model("meetings", "Role")
    MeetingTypeItem = apps.get_model("meetings", "MeetingTypeItem")

    timer = Role.objects.filter(name=TIMER).first()
    defaults = {f: getattr(timer, f) for f in CLONED_FIELDS} if timer else {}
    co_timer, _ = Role.objects.get_or_create(name=CO_TIMER, defaults=defaults)

    # Place a Co-Timer sign-up slot alongside the main Timer, in the session
    # where the timer is introduced. Skip if that Timer line isn't found or a
    # Co-Timer line already exists there.
    if not timer:
        return
    timer_item = (
        MeetingTypeItem.objects.filter(
            meeting_type__name=MEETING_TYPE, role=timer, session__name=SESSION
        )
        .order_by("order")
        .first()
    )
    if timer_item is None:
        return
    MeetingTypeItem.objects.get_or_create(
        meeting_type=timer_item.meeting_type,
        role=co_timer,
        session=timer_item.session,
        defaults={"count": 1, "order": timer_item.order + 1, "in_person": True},
    )


def remove_co_timer(apps, schema_editor):
    Role = apps.get_model("meetings", "Role")
    MeetingTypeItem = apps.get_model("meetings", "MeetingTypeItem")
    MeetingRole = apps.get_model("meetings", "MeetingRole")

    co_timer = Role.objects.filter(name=CO_TIMER).first()
    if co_timer is None:
        return
    MeetingTypeItem.objects.filter(role=co_timer).delete()
    # Role.role is PROTECT-ed by MeetingRole; only remove the role if no
    # meeting instance already references it.
    if not MeetingRole.objects.filter(role=co_timer).exists():
        co_timer.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0033_role_single_holder_all_slots"),
    ]

    operations = [
        migrations.RunPython(add_co_timer, remove_co_timer),
    ]
