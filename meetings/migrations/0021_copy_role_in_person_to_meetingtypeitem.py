from django.db import migrations


def copy_role_in_person_to_mti(apps, schema_editor):
    """Seed each MeetingTypeItem's new in_person from its Role's current value."""
    MeetingTypeItem = apps.get_model("meetings", "MeetingTypeItem")
    for mti in MeetingTypeItem.objects.select_related("role"):
        mti.in_person = mti.role.in_person
        mti.save(update_fields=["in_person"])


def copy_mti_in_person_back_to_role(apps, schema_editor):
    """Reverse: write each Role's in_person back from any one of its MTIs."""
    MeetingTypeItem = apps.get_model("meetings", "MeetingTypeItem")
    Role = apps.get_model("meetings", "Role")
    for role in Role.objects.all():
        mti = MeetingTypeItem.objects.filter(role=role).first()
        if mti is not None:
            role.in_person = mti.in_person
            role.save(update_fields=["in_person"])


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0020_add_in_person_to_meetingtypeitem"),
    ]

    operations = [
        migrations.RunPython(
            copy_role_in_person_to_mti, copy_mti_in_person_back_to_role
        ),
    ]
