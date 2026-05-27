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
