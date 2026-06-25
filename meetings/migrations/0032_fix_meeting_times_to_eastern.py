"""Re-localize existing Meeting.date values from UTC to Cambridge time.

Historical meetings were imported via a code path that combined the naive
6:45 PM wall-clock with ``make_aware`` while the project ran in UTC, so they
were stored as 18:45 UTC instead of the intended 6:45 PM Eastern. Now that the
project TIME_ZONE is America/New_York, re-stamp each row's wall-clock as
Eastern (DST-aware) so the stored instant — and every displayed time — is
correct.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from django.db import migrations

EASTERN = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def utc_walltime_to_eastern(apps, schema_editor):
    Meeting = apps.get_model("meetings", "Meeting")
    for meeting in Meeting.objects.all():
        wall = meeting.date.astimezone(UTC).replace(tzinfo=None)
        Meeting.objects.filter(pk=meeting.pk).update(
            date=wall.replace(tzinfo=EASTERN))


def eastern_walltime_to_utc(apps, schema_editor):
    Meeting = apps.get_model("meetings", "Meeting")
    for meeting in Meeting.objects.all():
        wall = meeting.date.astimezone(EASTERN).replace(tzinfo=None)
        Meeting.objects.filter(pk=meeting.pk).update(
            date=wall.replace(tzinfo=UTC))


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0031_meeting_zoom_meeting_id_alter_meeting_zoom_link"),
    ]

    operations = [
        migrations.RunPython(utc_walltime_to_eastern, eastern_walltime_to_utc),
    ]
