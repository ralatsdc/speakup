"""Replace the single Role.time_minutes with a min/max duration range, rename
MeetingRole.time_minutes -> exact_minutes (an optional override), and seed
sensible per-role ranges. Runs on deploy; role names match production."""
from django.db import migrations, models

# Standard duration ranges (minutes). Roles omitted here stay 0/0 = untimed
# (Zoom Host, Zoom Wizard, Room Leader, President).
RANGES = {
    "Speaker": (5, 7),
    "Ranter": (2, 3),
    "Evaluator (Speech)": (2, 3),
    "Evaluator (Rant)": (1, 2),
    "Evaluator (Table Topic)": (2, 3),
    "General Evaluator": (3, 5),
    "Topicmaster": (10, 10),
    "Toastmaster": (3, 4),
    "Grammarian": (1, 2),
    "Ah-Um Counter": (1, 2),
    "Word of the Day Presenter": (1, 2),
    "Humorist": (1, 2),
    "Round Robin Leader": (20, 20),
    "Improv Exercise Leader": (15, 15),
    "Timer": (2, 2),
}


def seed_ranges(apps, schema_editor):
    Role = apps.get_model("meetings", "Role")
    for name, (lo, hi) in RANGES.items():
        Role.objects.filter(name=name).update(min_minutes=lo, max_minutes=hi)


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0028_role_show_on_agenda"),
    ]

    operations = [
        migrations.RemoveField(model_name="role", name="time_minutes"),
        migrations.AddField(
            model_name="role",
            name="min_minutes",
            field=models.PositiveIntegerField(
                default=0, help_text="Standard minimum duration in minutes (0 = untimed)."
            ),
        ),
        migrations.AddField(
            model_name="role",
            name="max_minutes",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Standard maximum duration in minutes; equal to the "
                "minimum for a fixed duration.",
            ),
        ),
        migrations.RenameField(
            model_name="meetingrole", old_name="time_minutes", new_name="exact_minutes"
        ),
        migrations.AlterField(
            model_name="meetingrole",
            name="exact_minutes",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Exact duration for this assignment, overriding the "
                "role's standard range. 0 = use the range.",
            ),
        ),
        migrations.RunPython(seed_ranges, migrations.RunPython.noop),
    ]
