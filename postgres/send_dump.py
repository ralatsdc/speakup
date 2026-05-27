#!/usr/bin/env python3
"""Email a Postgres dump file to the club's backup mailbox.

Invoked by ``pg.sh -d`` after a successful ``pg_dump``. Self-contained: no
Django, no third-party packages, no system mail relay. SMTP is Gmail over
TLS, authenticated with a Gmail "App password" stored in ``postgres/.env``.

Two distinct accounts by design:

* ``BACKUP_EMAIL_FROM`` — the *sender*. A developer-owned Gmail with 2SV
  enabled and an App password the script logs in with. Officers never
  touch it.
* ``BACKUP_EMAIL_TO`` — the *recipient(s)*. One or more comma-separated
  addresses. Typically a shared club mailbox officers can sign in to
  without 2SV; can also include personal addresses for redundancy.

See ``docs/railway-setup.md`` → "Backup mailbox (Gmail)" for the one-time
account setup.

Exit codes
----------
0  email sent (or skipped because BACKUP_EMAIL_TO is unset).
1  configuration error or send failure. Stderr carries the reason.

Usage
-----
    python send_dump.py path/to/dump-YYYY-MM-DDTHH:MM:SS.tar
"""

import os
import smtplib
import socket
import sys
from email.message import EmailMessage
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_env(path):
    """Minimal ``.env`` parser. Sets each ``KEY=VALUE`` line into ``os.environ``
    only if KEY isn't already in the environment, so launchd-supplied vars
    win. Skips blank lines and ``#`` comments. Strips matching surrounding
    quotes from VALUE.
    """
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def main(argv):
    if len(argv) != 2:
        print("usage: send_dump.py <dump-file>", file=sys.stderr)
        return 1

    dump_path = Path(argv[1]).resolve()
    if not dump_path.is_file():
        print(f"send_dump: dump file not found: {dump_path}", file=sys.stderr)
        return 1

    _load_env(SCRIPT_DIR / ".env")

    sender = os.environ.get("BACKUP_EMAIL_FROM", "").strip()
    password = os.environ.get("BACKUP_EMAIL_APP_PASSWORD", "").strip()
    raw_to = os.environ.get("BACKUP_EMAIL_TO", "").strip()
    recipients = [r.strip() for r in raw_to.split(",") if r.strip()]
    if not recipients:
        # Email shipment is opt-in: an unset recipient list means "don't
        # try". Useful before the Gmail mailbox is provisioned so the dump
        # itself still runs to completion.
        print(
            "send_dump: BACKUP_EMAIL_TO unset; skipping email step.",
            file=sys.stderr,
        )
        return 0
    if not sender or not password:
        print(
            "send_dump: BACKUP_EMAIL_FROM and BACKUP_EMAIL_APP_PASSWORD must "
            "both be set when BACKUP_EMAIL_TO is configured.",
            file=sys.stderr,
        )
        return 1

    msg = EmailMessage()
    msg["Subject"] = f"Speak Up Cambridge backup {dump_path.name}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        "Nightly Postgres dump attached.\n\n"
        f"Host:     {socket.gethostname()}\n"
        f"File:     {dump_path.name}\n"
        f"Size:     {dump_path.stat().st_size:,} bytes\n\n"
        "To restore: see postgres/pg.sh -r <file>.\n"
    )
    with dump_path.open("rb") as fh:
        msg.add_attachment(
            fh.read(),
            maintype="application",
            subtype="x-tar",
            filename=dump_path.name,
        )

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"send_dump: SMTP send failed: {exc}", file=sys.stderr)
        return 1

    print(f"send_dump: emailed {dump_path.name} to {msg['To']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
