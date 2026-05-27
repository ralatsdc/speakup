"""Rename Role.is_speech_role to Role.shows_pathways_fields and audit the
existing data.

The field's only functional purpose was gating the sign-up dialog's
Pathways fields, but historical data had it flagged on every role —
including ones (Timer, Grammarian, Zoom Host, …) that never present a
Pathways project. Rename to reflect the actual semantic and reset the
flag to True only on roles that really present Pathways material.
"""
from django.db import migrations, models


# Existing Role names that should keep the flag set after the audit.
# Anything not in this list gets reset to False.
PATHWAYS_ROLE_NAMES = ("Speaker", "Ranter", "Humorist")


def audit_pathways_roles(apps, schema_editor):
    Role = apps.get_model("meetings", "Role")
    Role.objects.all().update(shows_pathways_fields=False)
    Role.objects.filter(name__in=PATHWAYS_ROLE_NAMES).update(
        shows_pathways_fields=True
    )


def restore_blanket_flag(apps, schema_editor):
    """Reverse the audit by re-flagging every role (pre-rename state)."""
    Role = apps.get_model("meetings", "Role")
    Role.objects.all().update(shows_pathways_fields=True)


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0024_add_is_evaluated_role"),
    ]

    operations = [
        # Preserve existing column + values via RenameField (not Remove+Add,
        # which Django auto-generated because of an unrelated help_text
        # change).
        migrations.RenameField(
            model_name="role",
            old_name="is_speech_role",
            new_name="shows_pathways_fields",
        ),
        migrations.AlterField(
            model_name="role",
            name="shows_pathways_fields",
            field=models.BooleanField(
                default=False,
                help_text="When True, the sign-up dialog asks the member for "
                "their Pathways path/level/project for this role (Speaker, "
                "Ranter, etc.).",
            ),
        ),
        migrations.RunPython(audit_pathways_roles, restore_blanket_flag),
    ]
