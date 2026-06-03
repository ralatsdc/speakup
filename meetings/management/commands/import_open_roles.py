"""
Import role assignments from "Speak Up Cambridge Open Roles.txt" into the
meeting tables.

DRY-RUN by default: prints exactly what it would create/assign and rolls back.
Pass --commit to persist (wrapped in a single transaction).

Rules (agreed with the club owner):
  * Meeting / MeetingSession / MeetingRole / Attendance are disposable and get
    rebuilt from scratch. Role / Session / MeetingType / User are read-only.
  * Window: meetings on/after 2024-07-01 only.
  * Names resolve to ACTIVE users only (import_scripts.resolve); inactive
    members and non-DB guests are dropped. No users are created.
  * Each Meeting is created with its mapped MeetingType, whose post_save signal
    generates the template slot slate. Parsed assignments fill those slots by
    role in listed order; extras beyond the template add overflow rows.
  * Past meetings (date < today) drop unfilled slots and are skipped entirely
    if no active user was assigned. Upcoming meetings keep open slots and are
    created regardless.
"""

import datetime as dt
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone

from members.models import User
from meetings.models import (
    Attendance, Meeting, MeetingRole, MeetingSession, MeetingType, Role,
    RoleGuideEmailLog, send_first_time_role_email_on_assignment,
)
from import_scripts import parse_open_roles as P
from import_scripts import resolve as R

CUTOFF = dt.date(2024, 7, 1)
MEETING_TIME = dt.time(18, 45)  # 6:45 PM start


class _Rollback(Exception):
    """Raised to abort the transaction in dry-run mode."""


class Command(BaseCommand):
    help = "Import role assignments from the Open Roles doc (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true",
            help="Persist changes. Without this flag, runs a dry-run and "
                 "rolls back.")
        parser.add_argument(
            "--inspect", metavar="YYYY-MM-DD", default=None,
            help="Print the full built role list for the meeting on this date "
                 "(while still in the transaction) for verification.")

    # -- parsing -----------------------------------------------------------

    def parse_window(self):
        tokens = P.tokenize(P.SRC)
        meetings, _ = P.assemble(P.split_blocks(tokens))
        P.infer_years(meetings)
        out = []
        for m in meetings:
            try:
                d = dt.date(m["year"], m["mon"], m["day"])
            except ValueError:
                continue
            # Past-but-empty meetings are skipped later (Phase A); upcoming
            # empties are kept so their open slots exist to sign up for.
            if d >= CUTOFF and m["type"] is not None:
                m["date"] = d
                out.append(m)
        out.sort(key=lambda m: m["date"])
        return out

    # -- main --------------------------------------------------------------

    def handle(self, *args, commit=False, inspect=None, **opts):
        today = timezone.localdate()
        meetings = self.parse_window()

        users = list(User.objects.all())
        active = [u for u in users if u.is_active]
        by_email = {u.email: u for u in users}
        roles_by_name = {r.name: r for r in Role.objects.all()}
        mtypes = {mt.name: mt for mt in MeetingType.objects.all()}

        # Phase A (no DB): resolve assignments + decide which meetings to build.
        plans = []
        dropped = defaultdict(int)  # raw name -> count, names with no active user
        for m in meetings:
            assigns = []  # (role_name, [User,...]) in parsed order
            for role_name, raws in m["roles"].items():
                if role_name not in roles_by_name:
                    self.stderr.write(f"  ! unknown role {role_name!r}, skipped")
                    continue
                resolved, seen = [], set()
                for raw in raws:
                    u = R.resolve(raw, active, users, by_email)
                    if u is None:
                        dropped[raw] += 1
                    elif u.id not in seen:
                        seen.add(u.id)
                        resolved.append(u)
                if resolved:
                    assigns.append((role_name, resolved))
            total = sum(len(us) for _, us in assigns)
            is_past = m["date"] < today
            if is_past and total == 0:
                continue  # past meeting with no active user -> skip
            plans.append({"m": m, "assigns": assigns, "is_past": is_past,
                          "total": total})

        # Phase B (DB, in a transaction).
        report = {"created": 0, "assigned": 0, "overflow": 0, "open_kept": 0,
                  "emptied": 0, "guide_logs": 0, "attendance": 0}
        try:
            with transaction.atomic():
                self._wipe(report)
                # Don't fire onboarding emails for historical assignments.
                post_save.disconnect(send_first_time_role_email_on_assignment,
                                     sender=MeetingRole)
                try:
                    for plan in plans:
                        self._build_meeting(plan, mtypes, roles_by_name, report)
                    if commit:
                        report["guide_logs"] = self._backfill_guide_logs()
                    if inspect:
                        self._inspect(inspect)
                finally:
                    post_save.connect(send_first_time_role_email_on_assignment,
                                      sender=MeetingRole)
                if not commit:
                    raise _Rollback
        except _Rollback:
            pass

        self._print_report(plans, dropped, report, commit, today)

    # -- helpers -----------------------------------------------------------

    def _wipe(self, report):
        report["wiped"] = {
            "meetings": Meeting.objects.count(),
            "sessions": MeetingSession.objects.count(),
            "roles": MeetingRole.objects.count(),
            "attendance": Attendance.objects.count(),
        }
        # Meeting cascade removes sessions, roles and attendance.
        Meeting.objects.all().delete()

    def _build_meeting(self, plan, mtypes, roles_by_name, report):
        m = plan["m"]
        mt = mtypes.get(m["type"])
        when = timezone.make_aware(dt.datetime.combine(m["date"], MEETING_TIME))
        meeting = Meeting.objects.create(meeting_type=mt, date=when)
        report["created"] += 1

        # template slots created by the post_save signal, grouped by role
        slots = defaultdict(list)
        for mr in meeting.roles.order_by("sort_order"):
            slots[mr.role.name].append(mr)
        cursor = defaultdict(int)  # role -> next free slot index

        for role_name, resolved in plan["assigns"]:
            role_obj = roles_by_name[role_name]
            free = slots[role_name]
            sess = free[0].session if free else None
            for u in resolved:
                i = cursor[role_name]
                if i < len(free):
                    mr = free[i]
                    mr.user = u
                    mr.save(update_fields=["user"])
                else:
                    MeetingRole.objects.create(
                        meeting=meeting, role=role_obj, session=sess, user=u,
                        time_minutes=role_obj.time_minutes,
                        sort_order=900 + i)
                    report["overflow"] += 1
                cursor[role_name] += 1
                report["assigned"] += 1

        if plan["is_past"]:
            n = meeting.roles.filter(user__isnull=True).count()
            meeting.roles.filter(user__isnull=True).delete()
            report["emptied"] += n
            # Derive attendance: a role-holder necessarily attended. One row
            # per distinct user (the model's unique constraint enforces this).
            # Upcoming meetings get none — a sign-up isn't confirmed attendance.
            attendees = {u.id for _, us in plan["assigns"] for u in us}
            Attendance.objects.bulk_create(
                [Attendance(meeting=meeting, user_id=uid) for uid in attendees])
            report["attendance"] += len(attendees)
        else:
            report["open_kept"] += meeting.roles.filter(user__isnull=True).count()

    def _inspect(self, date_str):
        w = self.stdout.write
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            self.stderr.write(f"--inspect: bad date {date_str!r}")
            return
        qs = Meeting.objects.filter(date__date=d)
        w("")
        w(f"--- inspect {date_str} ({qs.count()} meeting(s)) ---")
        for meeting in qs:
            w(f"  {meeting}  type={meeting.meeting_type}")
            for mr in meeting.roles.select_related("role", "session", "user") \
                    .order_by("sort_order", "id"):
                who = f"{mr.user.first_name} {mr.user.last_name}" if mr.user \
                    else "— OPEN —"
                sess = mr.session.name if mr.session else "-"
                w(f"     [{sess:18}] {mr.role.name:22} : {who}")

    def _backfill_guide_logs(self):
        """Record (user, role) for every assignment so historical role-holders
        aren't re-onboarded by a future real assignment. Idempotent."""
        pairs = {(mr.user_id, mr.role_id)
                 for mr in MeetingRole.objects.filter(user__isnull=False)}
        existing = set(RoleGuideEmailLog.objects.values_list("user_id", "role_id"))
        new = [RoleGuideEmailLog(user_id=u, role_id=r)
               for (u, r) in pairs if (u, r) not in existing]
        RoleGuideEmailLog.objects.bulk_create(new, ignore_conflicts=True)
        return len(new)

    def _print_report(self, plans, dropped, report, commit, today):
        w = self.stdout.write
        mode = "COMMIT" if commit else "DRY-RUN (rolled back)"
        w("")
        w(f"=== import_open_roles  [{mode}] ===")
        w(f"would wipe: {report.get('wiped')}")
        w(f"meetings built: {report['created']}  "
          f"(of {len(plans)} planned in window)")
        w(f"assignments: {report['assigned']}  overflow rows: {report['overflow']}")
        w(f"attendance rows derived (past role-holders): {report['attendance']}")
        w(f"past empty slots dropped: {report['emptied']}  "
          f"upcoming open slots kept: {report['open_kept']}")
        if commit:
            w(f"role-guide logs backfilled: {report['guide_logs']}")
        w("")
        w("per-meeting:")
        for plan in plans:
            m = plan["m"]
            tag = "past" if plan["is_past"] else "UPCOMING"
            w(f"  {m['date']}  {m['type'][:18]:18} [{tag:8}] "
              f"assigned={plan['total']}")
        # Names that appeared but resolved to no active user (already reviewed,
        # shown again so a commit run is fully auditable).
        total_drops = sum(dropped.values())
        w("")
        w(f"dropped name-instances (inactive/guests/unmatched): {total_drops} "
          f"across {len(dropped)} distinct names")
        if not commit:
            w("")
            w("Dry-run only. Re-run with --commit to persist.")
