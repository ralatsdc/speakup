# Railway setup runbook

What to do if you need to recreate the SpeakUp production environment
from scratch — new Railway project, new Postgres, new domain. Most of
the deploy configuration already lives in code (`railway.toml`,
`requirements.txt`, `config/settings.py`); this document covers the
one-time provisioning steps that can't live in the repo.

The canonical list of environment variables the app expects is in
[`.env.example`](../.env.example). Treat this runbook as a walkthrough
that pairs with that checklist.

---

## 1. Create the Railway project and service

1. **New project** in the Railway dashboard. Connect it to this Git
   repo and pick the production branch.

2. Railway autodetects Python via `requirements.txt` and uses the
   `[deploy] startCommand` from `railway.toml`:

   ```
   python manage.py collectstatic --noinput \
     && python manage.py migrate --noinput \
     && gunicorn config.wsgi
   ```

3. **Add the Postgres plugin** (Add Service → Database → Postgres).
   Railway auto-injects `DATABASE_URL` into the web service.

## 2. Set environment variables

Use the **Variables** tab on the web service. The full list is in
`.env.example` — work top to bottom. Required for a working production
deploy:

| Variable | Notes |
| --- | --- |
| `SECRET_KEY` | `python -c 'import secrets; print(secrets.token_urlsafe(64))'` |
| `DEBUG` | Leave unset (default is False). |
| `ALLOWED_HOSTS` | Railway domain + custom domain, comma-separated. |
| `CSRF_TRUSTED_ORIGINS` | Same hosts with `https://` scheme. |
| `SITE_URL` | Public origin used for email links. |
| `BREVO_API_KEY` | Brevo → SMTP & API → API Keys. |
| `DEFAULT_FROM_EMAIL` | Must match a Brevo-verified sender. |
| `AWS_STORAGE_BUCKET_NAME` | See section 3. Omit if you're not using S3 yet. |
| `AWS_S3_REGION_NAME` | e.g. `us-east-1`. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | IAM user credentials from section 3. |

The CLI-friendly alternative, once you have a populated production
`.env` locally:

```sh
railway link            # one time, picks the service
while IFS='=' read -r key value; do
    case "$key" in ''|\#*) continue ;; esac
    railway variables --set "$key=$value"
done < .env.production
```

Never commit a real `.env` — see the credentials-rotation note in the
project memory.

## 3. S3 bucket and IAM user

Role guidance PDFs uploaded through the admin (`Role.guidance_document`)
are stored in S3. The bucket holds no public assets — the FileField is
read server-side to attach to outbound email, never linked.

### Bucket

1. S3 console → **Create bucket**.
2. **Bucket type**: General purpose. **Bucket name**: `speakup-club-media`
   (globally unique).
3. **Region**: `us-east-1` (or your choice — keep `AWS_S3_REGION_NAME`
   in sync).
4. **Object Ownership**: ACLs disabled (Bucket owner enforced). With
   this setting, every uploaded object is automatically owned by the
   bucket and ACLs are not used — access is governed by bucket and IAM
   policies. `config/settings.py` accordingly does *not* pass a
   `default_acl` to django-storages.
5. **Block all public access**: leave ON. The bucket refuses all public
   reads.
6. **Bucket versioning**: disabled. Django-storages is configured with
   `file_overwrite=False`, which renames a colliding upload rather than
   replacing it, so versioning isn't needed against accidental clobbers.
7. **Default encryption**: SSE-S3. Enable Bucket Key (default).

### IAM user + policy

1. IAM console → **Create user** named e.g. `speakup-railway`.
2. Skip console access; this user only needs programmatic credentials.
3. Attach an **inline policy** with the JSON below (substitute your
   bucket name). The policy is intentionally narrow:
   `s3:ListBucket` on the bucket itself, plus
   `Get/Put/Delete/HeadObject` on `role_guides/*` only. The user can't
   touch any other prefix, can't read public credentials, can't list
   other buckets.

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "ListBucket",
         "Effect": "Allow",
         "Action": ["s3:ListBucket"],
         "Resource": ["arn:aws:s3:::speakup-club-media"],
         "Condition": {
           "StringLike": {"s3:prefix": ["role_guides/*"]}
         }
       },
       {
         "Sid": "ObjectRW",
         "Effect": "Allow",
         "Action": [
           "s3:GetObject",
           "s3:PutObject",
           "s3:DeleteObject"
         ],
         "Resource": ["arn:aws:s3:::speakup-club-media/role_guides/*"]
       }
     ]
   }
   ```

4. **Create access key** for the user (Use case: "Application running
   outside AWS"). Copy the access key ID and secret key into the
   Railway environment as `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY`. These are the only place AWS sees the
   secret — store a copy in your password manager.

### Verify

After deploying:

```sh
railway run python manage.py shell -c '
from django.core.files.storage import default_storage
print(type(default_storage).__name__)  # expect S3Storage
'
```

Upload a guidance PDF through the Role admin and confirm the object
appears under `role_guides/` in the S3 console.

## 4. Domain and TLS

Railway issues a `*.up.railway.app` subdomain automatically. To bind a
custom domain, add it under **Settings → Domains** and set the CNAME at
your registrar. Update `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and
`SITE_URL` to include the new domain.

## 5. First deploy

Push the production branch. Railway builds the image, runs the
`startCommand`, and exposes the web service. The Postgres plugin's
data persists across deploys.

For the very first deploy you'll likely want to:

1. `railway run python manage.py createsuperuser` once over CLI.
2. Upload your role-guide PDFs via the Role admin.
3. Create the initial `MeetingType` and template `Session` rows
   (matches what the local fixtures look like).

## 6. Releases and rollback

Every merge to the production branch **is** a deploy: Railway rebuilds and
runs the `startCommand` (including `migrate --noinput`). Tag each one so
"what was live on date X" is reproducible and rollbacks have an exact target.

### Release checklist (per merge to `main`)

1. Pick the SemVer bump (`vMAJOR.MINOR.PATCH`).
2. Note any **new migrations** the PR adds — this is what decides whether a
   later rollback needs database work (see below).
3. Squash-merge the PR → Railway deploys automatically.
4. Tag the merge commit and push:
   ```sh
   git checkout main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z — <summary>"
   git push origin vX.Y.Z
   ```
5. Create the GitHub Release (`gh release create vX.Y.Z ...`). In the notes,
   **list the new migrations** and a one-line rollback note.

### Rolling back to an older release

Code and database roll back **separately**. For the code, easiest first:

- **Railway dashboard** — Deployments → open an older deployment →
  **Redeploy**. Re-runs that exact build; no git changes.
- **From a tag** — deploy a specific release directly, bypassing the
  GitHub trigger:
  ```sh
  git checkout vX.Y.Z
  railway up
  git switch main
  ```
- **`git revert`** the bad commits on `main` and push (forward-only; never
  force-push `main` backward — it rewrites shared history).

**The catch — the database does not roll back with the code.** `migrate`
only moves forward, so if the release you're leaving **added or changed
schema**, older code may run against a newer schema and break or lose data.
When schema changed, choose one:

- **Preferred:** keep migrations backward-compatible (additive — new nullable
  columns; no drops/renames alongside the code that needs them), so old code
  still runs on the new schema and a code-only rollback just works.
- **Reverse the migration:** `python manage.py migrate <app> <previous>` —
  but reversing can be lossy (a dropped column's data is gone).
- **Restore a database dump** that matches the older release (see the backup
  mailbox and restore sections below).

## 7. Backup mailbox (Gmail)

Nightly Postgres backups produced by `postgres/pg.sh -d` are tar files
on the developer's Mac (a launchd job runs the dump). To survive a
lost laptop and to give other officers access without giving them shell
access, each new dump is emailed by `postgres/send_dump.py` to a shared
club mailbox.

The setup uses **two separate Gmail accounts** to keep officer access
free of 2SV friction:

| Account | Used for | 2SV | Who knows the password |
| --- | --- | --- | --- |
| **Sender** (developer's Gmail) | SMTP login from the script | Required (Google policy on App passwords) | Just you. Officers never see it. |
| **Recipient** (club Gmail) | Archive officers read backups from | Off | Officers, via the club password manager. |

The sender's 2SV is a one-time developer-only concern — the script
uses an App password, never the human Gmail password. The recipient
mailbox stays simple for officers: just a normal Gmail sign-in.

### Sender setup (one-time, developer-only)

1. Pick any Gmail you already control. 2SV must already be on (or
   turn it on now: Google Account → Security → 2-Step Verification).
2. Generate an **App password** at
   https://myaccount.google.com/apppasswords.
   **App name**: `SpeakUp backup`. Google displays the 16-character
   password once — copy it now.
3. In `postgres/.env`:

   ```
   BACKUP_EMAIL_FROM=<your-gmail-address>
   BACKUP_EMAIL_APP_PASSWORD=<the-16-char-token>
   ```

4. Also store the App password in the password manager. Revoking it
   on the same Google page instantly disables the script's send path
   without touching the rest of the account.

### Recipient mailbox setup (one-time, shared with officers)

1. Create a new Gmail account, e.g. `speakup.cambridge.backups@gmail.com`.
2. Pick a long random password; store it in the club password manager
   so officers who need backup access can retrieve it.
3. Leave 2-Step Verification **off** for this account. Officers will
   sign in with just the password, and Google may prompt them with a
   "trust this device?" challenge on first sign-in from a new browser.
4. In `postgres/.env`:

   ```
   BACKUP_EMAIL_TO=<the-club-gmail-address>
   ```

   `BACKUP_EMAIL_TO` is comma-separated — if you ever want backups
   mirrored to a personal address as well, add it here.

### Verify

```sh
cd postgres
./pg.sh -d
```

Check the club mailbox via webmail — you should see one new message
with the `dump-*.tar` attached. Stderr will read
`send_dump: emailed dump-... to <address>` on success.

If the email step fails (wrong App password, no network, etc.) the
local tar still lands in `postgres/` — the dump itself never depends
on the email succeeding.

### Retrieving a backup

Any officer with the mailbox credentials can:

1. Sign in to webmail at https://mail.google.com.
2. Search for `has:attachment` (or the date of interest).
3. Download the `.tar` attachment.
4. Hand the file to whoever's doing the restore.

The mailbox is search-indexed and 15 GB free — at one ~MB dump per
day that's years of headroom.

## 8. Restore verification (`pg.sh -t`)

A backup that's never been restored is a backup you can't trust.
`pg.sh -t` exercises the full restore path against an *ephemeral*
Postgres container, so we know every nightly dump is actually
restorable without risking the live database.

What it does, in order:

1. Finds the newest `dump-*.tar` in `postgres/`.
2. Starts a throwaway `postgres:17` container named
   `speakup-pg-restore-test`, listening on `127.0.0.1:55432`.
3. Waits up to 30 seconds for the server to accept connections.
4. Runs `pg_restore` against it.
5. Runs sanity SELECTs: row counts on `members_user`,
   `meetings_meeting`, `meetings_attendance`, `meetings_meetingrole`,
   plus the `MAX(date)` of meetings. Each statement runs with
   `ON_ERROR_STOP=1` so a missing table aborts immediately.
6. Stops the container (which removes it — `docker run --rm`).

Requires **Docker Desktop** installed and running. The first invocation
pulls `postgres:17` (~150 MB); subsequent runs use the cached image.

### Manual run

```sh
cd postgres
./pg.sh -t
```

Expected output ends with:

```
pg.sh: restore-test PASSED for dump-YYYY-MM-DDTHH:MM:SS.tar.
```

Failure modes:

- `pg.sh: docker not found in PATH` — install Docker Desktop and
  ensure `/usr/local/bin/docker` is on `PATH`.
- `pg.sh: docker daemon not running` — start Docker Desktop.
- `pg.sh: no dump-*.tar files…` — run `./pg.sh -d` first to produce one.
- `pg.sh: container never became ready` — the postgres image failed to
  boot in 30 seconds. Almost always a port conflict on 55432; check
  with `lsof -i :55432`.
- `pg.sh: pg_restore exited non-zero` — the dump is corrupt or was
  produced against an incompatible schema version.
- `pg.sh: sanity checks failed` — restore "succeeded" but a required
  table is missing or empty. Likely a partial dump.

### Scheduled run

A second launchd plist (`postgres/com.user.pgrestoretest.plist`) fires
`pg.sh -t` at 16:00 daily — one hour after the dump at 15:00. Decoupling
the two means a failed dump doesn't block the verification, and a
failed verification still leaves the previous successful dump intact.

Install once:

```sh
cp postgres/com.user.pgrestoretest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.pgrestoretest.plist
```

Logs land in `/tmp/com.user.pgrestoretest.{out,err}`. Tail them after a
day or two to confirm it's running.

## What we don't yet automate

- IAM/bucket creation. The JSON is in this doc; running it via
  `aws` CLI or Terraform is a future improvement, not currently
  worthwhile.
- A `scripts/provision-railway.sh` helper that sets every variable
  from a local `.env` in one call. The CLI snippet in section 2 is
  the manual equivalent — promote it to a script if you find
  yourself running it more than twice.
- A "scratch" Railway environment for staging. Worth standing up if
  the club ever wants to test changes before they hit production.
