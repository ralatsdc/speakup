# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run dev server
python manage.py runserver

# Run all tests
python manage.py test

# Run tests for one app
python manage.py test meetings

# Run a single test class
python manage.py test meetings.tests.MeetingSignalTest

# Migrations
python manage.py makemigrations
python manage.py migrate
```

## Architecture

Django 5.2 Toastmasters club management app. Config lives in `config/`. Custom user model: `members.User` (AUTH_USER_MODEL = "members.User").

### Apps

- **core** — Base template (`base.html`), landing page, help pages, registration templates
- **members** — Custom User model with `is_guest`, `is_officer`, `mentor`, `join_date`; admin has CSV import/export
- **meetings** — Largest app: meeting scheduling, role sign-ups, attendance kiosk, agenda generation
- **communications** — Announcement model with audience filtering and email dispatch
- **education** — Empty placeholder

### Meeting Data Model (two-layer pattern)

**Template layer** (reusable config): `Role`, `Session`, `MeetingType` → `MeetingTypeSession`, `MeetingTypeItem`

**Instance layer** (per-meeting): `Meeting`, `MeetingSession`, `MeetingRole`, `Attendance`

A `post_save` signal on `Meeting` auto-populates `MeetingSession` and `MeetingRole` rows from the `MeetingType` template. `MeetingRole.user` is nullable (null = open slot).

### Business Logic Locations

- `meetings/services.py` — Guest-to-user conversion
- `meetings/utils.py` — `send_meeting_reminders()`, `send_meeting_feedback()`
- `communications/utils.py` — `send_announcement()`
- `communications/individual.py` — one-at-a-time announcement sending and its progress rules

### Frontend

Bootstrap 5 + HTMX 1.9, no JS framework. HTMX partials in `meetings/templates/meetings/partials/` handle role toggle, note editing, and kiosk check-in. CSRF token set globally via `hx-headers` on `<body>`. Server-triggered alerts use `HX-Trigger: showAlert`.

Bootstrap, HTMX, and the webfonts are **self-hosted** — `core/static/core/vendor/`
and `core/static/core/fonts/`, with `@font-face` at the top of `custom.css`.
Don't reintroduce CDN `<link>`/`<script>` tags in `<head>`. The site once went
dark on the meeting venue's wifi while the app was demonstrably serving 200s
from that same network; a CDN fetch on the critical render path was the most
likely cause but was never confirmed. Self-hosting removes the class of failure
either way, and the app renders from one origin.

### Permission Flags

- `is_guest` — Cannot sign up for roles; excluded from some email audiences
- `is_officer` — Can edit any role's notes; bypass one-role-per-meeting limit
- `is_staff` — Django admin access
- `is_superuser` — Bypasses all permission checks

### Settings

`DEBUG` env var drives the dev/deploy split. When `DEBUG=False`: SSL redirect, secure cookies, Brevo email backend, WhiteNoise static compression. Database configured via `DATABASE_URL` (defaults to SQLite).

### Admin buttons and links

How a control looks shows what kind of action it is. Use Django admin's own
styles; don't add per-feature colors or inline `style` colors.

| Style | How | Meaning |
|---|---|---|
| Dark filled | `class="default"` | The main action, at most one per group. On edit pages that is Save |
| Teal filled | plain `input[type=submit]`, or `<button class="button">` | Another action that changes something or leads to one, including controls that filter what's shown |
| Gray filled | `class="exit"` | Leave without sending or recording anything (Cancel, Finish later) |
| Red | Django's delete styles | Delete or destroy |
| Text link | `<a>` | Only goes to another page |

A button that only opens the review-before-send page is named "Review …" with
an ellipsis, not "Send …".

A form that sends email must start with `<button type="submit" disabled
hidden></button>`. Otherwise pressing Enter in a text field clicks the first
submit button, which sends.

Prefer `input[type=submit]`. Admin doesn't style a bare `<button>`, even with
`class="default"`, and `<button class="button">` renders smaller, so keep that
for compact controls (Filter, Put back). `.exit` is currently defined only for the
email pages, in `communications/admin/_email_styles.html`.

### Email

Dev: console backend. Production: Brevo via `django-anymail`. Three workflows triggered from admin: meeting reminders, meeting feedback, announcements. All use `send_mass_mail()`.

### Admin Customizations

- `MeetingAdmin` — Custom change form with "Review reminders…" and "Review feedback emails…" buttons
- `AttendanceAdmin` — Bulk action: "Convert selected guests to Users"
- `AnnouncementAdmin` — Custom "Save & review to send…" button (opens the review page; sending happens there); "Start from template" picker and "Save as template" action (`EmailTemplate`); one-at-a-time progress column and read-only delivery history
- `CustomUserAdmin` — CSV import/export, bulk make/remove guest/officer/active actions
