# SpeakUp Cambridge — Admin Guide

This guide covers the administrative features of SpeakUp, the Speak Up Cambridge Toastmasters club management app. Admin access requires a staff account (`is_staff = True`). All admin tasks are performed through the Django admin panel at `/admin/`.

---

## Getting Started

Log in at `/accounts/login/` with your staff credentials. You'll see an **Admin** link in the navigation bar that takes you to the admin panel.

---

## Managing Members

### Adding a New Member

1. Go to **Members > Users > Add User**.
2. Fill in username, first name, last name, and email.
3. A default password is pre-filled — the member should reset it on first login.
4. Under **Toastmasters Profile**, set:
   - **Is guest** — check this for visitors who haven't officially joined the club.
   - **Is officer** — check this for current club officers (grants extra permissions; see below).
   - **Join date**, **phone number**, **mentor**, and **notes** as needed.

### Bulk Import / Export

Members can be imported from or exported to CSV files using the **Import** and **Export** buttons on the Users list page. This is useful for onboarding multiple members at once.

### Member Roles and Permissions

| Flag | What It Grants |
|---|---|
| **Is staff** | Access to the admin panel and all administrative functions |
| **Is officer** | Can edit notes on any meeting role; can sign up for multiple roles per meeting |
| **Is guest** | Cannot sign up for meeting roles; excluded from some email broadcasts |
| **Is active** | Unchecking this disables the account without deleting it |

---

## Setting Up Meeting Templates

Before scheduling meetings, configure the building blocks: **Roles**, **Sessions**, and **Meeting Types**.

### Roles

Go to **Meetings > Roles** to create the roles used at meetings (e.g., Toastmaster, Timer, Grammarian, Speaker).

Each role has:
- **Name** — displayed on agendas and sign-up sheets.
- **Is speech role** — marks this as a prepared speech slot.
- **Points** — point value for participation tracking.
- **Time minutes** — default time allotted.
- **In person** — whether this role requires physical presence.

### Sessions

Go to **Meetings > Sessions** to create reusable meeting segments (e.g., Table Topics, Prepared Speeches, Break, Business).

Each session has:
- **Name** — displayed on the agenda.
- **Duration minutes** — how long this segment typically lasts.
- **Takes roles** — whether roles can be assigned within this session.

### Meeting Types

Go to **Meetings > Meeting Types** to create reusable meeting templates. A meeting type combines sessions and roles into a standard format.

- Add **sessions** (in order) to define the meeting structure.
- Add **items** to specify how many of each role are needed.
- Set an optional **Zoom link** that will be inherited by meetings of this type.

---

## Scheduling Meetings

### Creating a Meeting

1. Go to **Meetings > Meetings > Add Meeting**.
2. Select a **meeting type** — sessions and roles will be auto-populated from the template.
3. Set the **date**.
4. Optionally fill in **theme**, **word of the day**, and **Zoom link** (overrides the meeting type default).

### Managing Roles and Assignments

On the meeting's edit page, you'll see inline sections for:

- **Meeting Sessions** — adjust order or notes for each session.
- **Meeting Roles** — assign members to roles, adjust time, set sort order, and add notes.

Each role has two note fields:
- **Notes** — visible on the public agenda (e.g., speech title and project).
- **Admin notes** — private; included in post-meeting feedback emails to the assignee.

---

## Meeting Day: The Check-In Kiosk

The kiosk at `/kiosk/` provides a public check-in interface that does not require login. It is designed to run on a tablet or laptop at the meeting venue.

- **Members** see a grid of names and tap to check in (toggles green/gray).
- **Guests** fill out a sign-in form with their name and email.

A QR code is displayed on the kiosk page linking to the public agenda.

### Converting Guests to Members

After a meeting, walk-in guests who signed in at the kiosk can be converted to user accounts:

1. Go to **Meetings > Attendances**.
2. Select the guest attendance records.
3. Choose the action **"Convert selected guests to Users"** and click Go.

This creates a new user account (marked as guest) with a random password. The new user can reset their password via the password reset flow.

---

## Communications

### Sending Meeting Reminders

On any meeting's edit page in the admin, click the **"Send Email Reminders"** button. This sends:

- **To members with assigned roles**: A reminder of their role, the meeting date/time, theme, and a link to the agenda.
- **To members without a role**: A request to help fill open roles, with a link to sign up.

### Sending Post-Meeting Feedback

After a meeting, fill in the **Admin notes** field on each role where you want to send feedback. Then click **"Send Feedback Emails"**. This sends:

- **To members with admin notes**: Their personalized feedback.
- **To guests who attended**: A thank-you email inviting them to return.

### Sending Announcements

1. Go to **Communications > Announcements > Add Announcement**.
2. Write a **subject** and **body**.
3. Choose an **audience**: all members, officers only, or guests only.
4. Save, then click **"Send Announcement"** on the announcement's edit page (or select announcements from the list and use the "Send selected announcements via Email" action).

The **sent at** timestamp is recorded automatically and displayed in the list view.

---

## Public Pages (No Login Required)

These pages are accessible to anyone, including non-members:

- **Meeting Agenda** (`/meeting/<id>/agenda/`) — displays the full agenda with roles, theme, word of the day, and Zoom link.
- **Agenda Download** (`/meeting/<id>/agenda/download/`) — downloads the agenda as a Word document (.docx).
- **Check-In Kiosk** (`/kiosk/`) — the meeting check-in interface described above.

---

## Email Configuration

- In **development** (DEBUG mode), emails are printed to the console instead of being sent.
- In **production**, emails are sent via the Brevo API. The `BREVO_API_KEY` and `DEFAULT_FROM_EMAIL` environment variables must be configured.

---

## Tips

- Use the **search** and **filter** features in admin list views to quickly find members, meetings, and attendance records.
- The **Attendance** admin supports filtering by meeting and by whether a user was present, making it easy to review attendance for specific meetings.
- When creating a meeting, the sessions and roles are populated automatically from the meeting type — you only need to adjust assignments and notes.
