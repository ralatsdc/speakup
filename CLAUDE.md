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

### Frontend

Bootstrap 5 + HTMX 1.9 (both via CDN), no JS framework. HTMX partials in `meetings/templates/meetings/partials/` handle role toggle, note editing, and kiosk check-in. CSRF token set globally via `hx-headers` on `<body>`. Server-triggered alerts use `HX-Trigger: showAlert`.

### Permission Flags

- `is_guest` — Cannot sign up for roles; excluded from some email audiences
- `is_officer` — Can edit any role's notes; bypass one-role-per-meeting limit
- `is_staff` — Django admin access
- `is_superuser` — Bypasses all permission checks

### Settings

`DEBUG` env var drives the dev/deploy split. When `DEBUG=False`: SSL redirect, secure cookies, Brevo email backend, WhiteNoise static compression. Database configured via `DATABASE_URL` (defaults to SQLite).

### Email

Dev: console backend. Production: Brevo via `django-anymail`. Three workflows triggered from admin: meeting reminders, meeting feedback, announcements. All use `send_mass_mail()`.

### Admin Customizations

- `MeetingAdmin` — Custom change form with "Send Email Reminders" and "Send Feedback Emails" buttons
- `AttendanceAdmin` — Bulk action: "Convert selected guests to Users"
- `AnnouncementAdmin` — Custom "Send Announcement" button
- `CustomUserAdmin` — CSV import/export, bulk make/remove guest/officer/active actions
