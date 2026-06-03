# SpeakUp — Developer Guide

A Django web application for managing Toastmasters club meetings, role sign-ups, attendance, and member communications.

## Stack

- **Django 5.2** — web framework
- **Bootstrap 5** — CSS (CDN)
- **HTMX 1.9** — dynamic partial updates (CDN)
- **Brevo (Sendinblue)** — transactional email via `django-anymail`
- **WhiteNoise** — static file serving in production
- **Railway** — deployment target (PostgreSQL, gunicorn)

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # edit as needed
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

SQLite is used by default. Set `DATABASE_URL` for PostgreSQL.

## Environment Variables

See `.env.example`. Key variables:

| Variable | Purpose | Default |
|---|---|---|
| `DEBUG` | Enables debug mode, console email backend | `False` |
| `SECRET_KEY` | Django secret key | insecure fallback |
| `DATABASE_URL` | Database connection string | SQLite |
| `BREVO_API_KEY` | Brevo API key (production email) | — |
| `DEFAULT_FROM_EMAIL` | Sender address for all outgoing email | `noreply@speakup.com` |
| `SITE_URL` | Base URL used in email links | `http://127.0.0.1:8000` |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `*` in production |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | `*.railway.app` |

`DEBUG` drives the deploy/dev split: when `False`, SSL redirect, secure cookies, Brevo email, and WhiteNoise compression are enabled.

## Project Structure

```
config/             Django project settings, urls, wsgi
core/               Base template, help pages, registration templates
members/            Custom User model (AbstractUser)
meetings/           Meeting scheduling, roles, attendance, kiosk, agenda
communications/     Announcement model and email sending
education/          Placeholder app (empty)
```

## Apps

### members

Custom user model extending `AbstractUser` with club-specific fields:

| Field | Type | Purpose |
|---|---|---|
| `is_guest` | bool | Guests cannot sign up for roles |
| `is_officer` | bool | Can edit any role's notes; bypass one-role-per-meeting limit |
| `phone_number` | str | Optional contact |
| `join_date` | date | Club membership date |
| `notes` | text | Admin notes about the member |
| `mentor` | FK(self) | Mentorship relationship |

Admin features: CSV import/export via `django-import-export`, custom fieldsets for Toastmasters profile.

### meetings

The largest app. Contains the data model for meeting templates and instances, plus all user-facing views.

**Template layer** (reusable configuration):
- `Role` — a role type (Toastmaster, Timer, Speaker, etc.) with name, points, time, in_person flag
- `Session` — a meeting segment (Table Topics, Prepared Speeches, Break)
- `MeetingType` — combines sessions and roles into a reusable template
  - `MeetingTypeSession` — ordered session within a type
  - `MeetingTypeItem` — "this type needs N of this role" in a given session

**Instance layer** (per-meeting data):
- `Meeting` — a scheduled meeting with date, theme, word of the day, zoom link
- `MeetingSession` — session instance for a specific meeting
- `MeetingRole` — role assignment slot; `user` is nullable (open slot vs. claimed)
  - `notes` — public (speech title, visible on agenda)
  - `admin_notes` — private (feedback, included in post-meeting emails)
- `Attendance` — who showed up; links to `User` for members, stores guest info for walk-ins
  - `UniqueConstraint` with condition ensures one attendance record per member per meeting while allowing multiple guest records

**Signal**: `post_save` on `Meeting` auto-populates `MeetingSession` and `MeetingRole` rows from the `MeetingType` template when a meeting is first created.

**Views** (`meetings/views.py`):

| URL | View | Auth | Purpose |
|---|---|---|---|
| `/` | `upcoming_meetings` | login_required | Paginated list of upcoming meetings with role tables |
| `/role/<id>/toggle/` | `toggle_role` | login_required | HTMX: claim or drop a role (enforces one-role limit, blocks guests) |
| `/role/<id>/note/` | `save_role_note` | login_required | HTMX: update notes on a role (assignee or officer) |
| `/meeting/<id>/agenda/` | `meeting_agenda` | public | Full agenda page |
| `/meeting/<id>/agenda/download/` | `meeting_agenda_download` | public | Agenda as .docx (`python-docx`) |
| `/kiosk/` | `checkin_kiosk` | public | Check-in kiosk for meeting day |
| `/kiosk/<id>/member/<uid>/` | `checkin_member` | public POST | HTMX: toggle member attendance |
| `/kiosk/<id>/guest/` | `checkin_guest` | public POST | HTMX: record walk-in guest |

**Services** (`meetings/services.py`):
- `convert_guest_attendance_to_user()` — creates a User account from a guest attendance record (used as an admin action)

**Email utilities** (`meetings/utils.py`):
- `send_meeting_reminders(meeting)` — pre-meeting: reminds assigned members, notifies unassigned members of open roles
- `send_meeting_feedback(meeting)` — post-meeting: sends `admin_notes` to role holders, thank-you emails to guests

**Admin customizations** (`meetings/admin.py`):
- Meeting change form has custom buttons: "Send Email Reminders" and "Send Feedback Emails"
- Attendance admin has a bulk action: "Convert selected guests to Users"
- MeetingRole admin has list-editable user and sort_order fields

### communications

- `Announcement` model with subject, body, audience (all/officers/guests), timestamps
- `send_announcement()` in `communications/utils.py` filters recipients by audience and dispatches email
- Admin has a custom "Send Announcement" button and a bulk send action

### core

- `base.html` — site-wide template with Bootstrap 5 navbar, HTMX setup, CSRF headers
- `help_page` view — renders admin or member help based on `user.is_staff`
- Registration templates for Django's built-in auth views (login, password reset flow)

## Frontend Patterns

- **No JavaScript framework** — Bootstrap 5 for styling, HTMX for interactivity
- **HTMX partials**: role sign-up, note editing, and kiosk check-in all swap individual DOM elements via `hx-post` / `hx-target` / `hx-swap="outerHTML"`
- **CSRF**: set globally via `hx-headers` on `<body>`
- **Server-triggered alerts**: views set `HX-Trigger: showAlert` header; base template listens with `addEventListener("showAlert", ...)`
- **Note editing**: inline show/hide toggle using `d-none` class, driven by `data-note-id` attributes and delegated click handlers in base template

## User Permission Model

| Flag | Effect |
|---|---|
| `is_staff` | Access to Django admin; sees "Admin" link in navbar |
| `is_superuser` | Bypasses all permission checks (unlimited role sign-ups) |
| `is_officer` | Can edit notes on any role; can sign up for multiple roles per meeting |
| `is_guest` | Cannot sign up for roles; excluded from some email audiences |
| `is_active` | Inactive users are excluded from email sends and attendance lists |

## Email

- **Development**: `console.EmailBackend` (prints to stdout)
- **Production**: Brevo via `django-anymail`; requires `BREVO_API_KEY`
- Three email workflows triggered from admin:
  1. Meeting reminders (pre-meeting)
  2. Meeting feedback (post-meeting)
  3. Announcements (ad hoc)

## Deployment

Configured for Railway:

- `Procfile`: `web: gunicorn config.wsgi`
- `railway.toml`: runs `collectstatic`, `migrate`, then `gunicorn` on deploy
- WhiteNoise serves static files with compression
- SSL termination at Railway's load balancer; `SECURE_PROXY_SSL_HEADER` trusts `X-Forwarded-Proto`

Set `DEBUG=False` and provide `DATABASE_URL`, `SECRET_KEY`, `BREVO_API_KEY`, `SITE_URL`, and `ALLOWED_HOSTS` as environment variables.

## Database Backups & Local Data (`postgres/pg.sh`)

Production runs PostgreSQL on Railway. `postgres/pg.sh` backs that database up
and produces a local SQLite copy to develop against. It reads the Railway
connection details from `postgres/.env` (`PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER`, `PGPASSWORD` — not committed).

| Option | Action |
|---|---|
| `-d` | Dump Railway to a timestamped `postgres/dump-<ts>.tar` (`pg_dump`, custom format) |
| `-c` | Convert Railway into a local SQLite DB and point `db.sqlite3` at it |
| `-r <file>` | Restore a `.tar` dump back into PostgreSQL (`pg_restore -c`) |
| `-u <file>` | Push a local SQLite DB up into Railway (the inverse of `-c`), with confirmation |
| `-p` | Prune old dumps via GFS (Grandfather-Father-Son) rotation, with confirmation |
| `-h` | Help; `-e`/`-x` add `set -e` / `set -x` |

Exactly one of `-d`, `-c`, `-r`, `-u`, `-p` per invocation. Run from the
`postgres/` directory:

```bash
cd postgres
bash pg.sh -d                 # nightly backup
bash pg.sh -c                 # refresh local db.sqlite3 from prod
bash pg.sh -u ../db.sqlite3   # push local db.sqlite3 up to prod (overwrites!)
bash pg.sh -p                 # tidy old dumps
```

A launchd agent (`postgres/com.user.pgdump.plist`) runs `pg.sh -d` daily at
15:00. Load/unload it with
`launchctl load|unload ~/Library/LaunchAgents/com.user.pgdump.plist`.

### How `-c` builds the SQLite file

`-c` does **not** translate the Postgres schema directly. It runs
`manage.py migrate` against a fresh SQLite file so **Django owns the schema**
(correct `PRIMARY KEY` / `UNIQUE` / foreign keys), then copies only data with
`dumpdata --natural-foreign | loaddata`. `contenttypes`, `auth.permission`,
`sessions.session`, and `admin.logentry` are excluded because `migrate`
re-seeds content types and permissions; `--natural-foreign` lets FKs to them
re-resolve against the fresh rows.

Earlier the script used `db-to-sqlite`, which infers the schema from data and
drops `PRIMARY KEY`/`UNIQUE` on some tables. SQLite doesn't enforce FKs during
normal ORM use, so the app still ran — but Django runs `PRAGMA
foreign_key_check` at the end of *every schema-altering migration*, which then
aborted with `foreign key mismatch`. Letting Django build the schema removes
that failure class. Do not revert `-c` to `db-to-sqlite`.

### Pushing a local SQLite DB up with `-u`

`-u` is the inverse of `-c`, using the same `dumpdata` exclusions and
`--natural-foreign` so the round trip is symmetric: it serializes the SQLite
rows, then `migrate`/`flush`/`loaddata` into Railway (`flush` clears existing
data and re-seeds content types + permissions via `post_migrate`). Because it
**overwrites all production data**, it prompts for confirmation first. Use it to
publish data prepared locally — e.g. after `manage.py import_open_roles
--commit`.

Caveat: `migrate` applies *local* migrations, so the local schema may lead
prod. That is fine for additive changes, but if a local migration removes or
renames a column still present on Railway, `dumpdata` against Railway will
fail until prod catches up.

Verify a generated file:

```bash
sqlite3 postgres/db-<ts>.sqlite3 "PRAGMA foreign_key_check;"   # empty = healthy
python manage.py migrate --check                               # exit 0
```
