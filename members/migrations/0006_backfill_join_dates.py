"""Backfill ``join_date`` for members who have none, estimating it from the
earliest meeting they attended (a safe floor — they were members by then).
One-time cleanup; members added later should get a real join date at signup.
Runs on deploy, where production already has the attendance data."""
from django.db import migrations
from django.db.models import Min


def backfill_join_dates(apps, schema_editor):
    User = apps.get_model("members", "User")
    Attendance = apps.get_model("meetings", "Attendance")
    for user in User.objects.filter(join_date__isnull=True):
        first = Attendance.objects.filter(user=user).aggregate(
            d=Min("meeting__date")
        )["d"]
        if first:
            user.join_date = first.date()
            user.save(update_fields=["join_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0005_officers_manage_users"),
        ("meetings", "0028_role_show_on_agenda"),
    ]

    operations = [
        migrations.RunPython(backfill_join_dates, migrations.RunPython.noop),
    ]
