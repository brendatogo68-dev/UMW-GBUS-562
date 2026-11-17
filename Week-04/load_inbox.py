"""Load the Hartwell HR sample emails into a Gmail sandbox inbox over IMAP.

Each .eml file in Week-04/hartwell-hr/sample-emails is placed directly in INBOX as an
UNREAD message dated today (IMAP APPEND). Nothing is sent: no SMTP, no outgoing mail.

The login is read at run time from Agent-Email.txt in the folder above the repository.
The password is only held in memory: it is never printed, logged or saved.

Accepted Agent-Email.txt layouts (blank lines and # comments are ignored):
    email: agent@gmail.com          or   agent@gmail.com
    password: abcd efgh ijkl mnop        abcd efgh ijkl mnop
(Keys may also be user/username/login/address and pass/app_password; "=" works like ":".
An optional "host:" line overrides imap.gmail.com.)

Gmail needs IMAP enabled and an app password (Google Account > Security > App passwords).

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe Week-04\\load_inbox.py             # load all sample emails
    .venv\\Scripts\\python.exe Week-04\\load_inbox.py --dry-run   # show what would be loaded; no sign-in
"""

import argparse
import imaplib
import re
import sys
import time
from email import policy
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = SCRIPT_DIR / "hartwell-hr" / "sample-emails"
LOGIN_FILE = SCRIPT_DIR.parent.parent / "Agent-Email.txt"
DEFAULT_HOST = "imap.gmail.com"
MAILBOX = "INBOX"

USER_KEYS = ("email", "email_address", "user", "username", "login", "address", "account")
PASS_KEYS = ("password", "pass", "app_password", "apppassword", "app password", "pwd")


def read_login():
    """Return (user, password, host) from LOGIN_FILE. Never prints the password."""
    if not LOGIN_FILE.is_file():
        sys.exit(f"Login file not found: {LOGIN_FILE}")
    lines = [ln.strip() for ln in LOGIN_FILE.read_text(encoding="utf-8-sig").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]

    user = password = None
    host = DEFAULT_HOST
    loose = []
    for ln in lines:
        m = re.match(r"^\s*([A-Za-z _-]+?)\s*[:=]\s*(.+)$", ln)
        key = m.group(1).strip().lower().replace("-", "_") if m else ""
        if m and key in USER_KEYS:
            user = m.group(2).strip()
        elif m and key in PASS_KEYS:
            password = m.group(2).strip()
        elif m and key in ("host", "server", "imap", "imap_host"):
            host = m.group(2).strip()
        else:
            loose.append(ln)

    # Fall back to a plain layout: address on one line, password on the next.
    if user is None and loose and "@" in loose[0]:
        user = loose.pop(0)
    if password is None and loose:
        password = loose.pop(0)

    if not user or not password:
        sys.exit(f"Could not find an email address and a password in {LOGIN_FILE.name}. "
                 "Use 'EMAIL_ADDRESS=...' and 'APP_PASSWORD=...' lines.")
    if user.count("@") != 1 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user):
        sys.exit(f"The email address in {LOGIN_FILE.name} is not a valid address "
                 "(it should look like name@gmail.com, with exactly one @).")
    # Google shows app passwords as four groups of four letters; IMAP wants them without spaces.
    if re.fullmatch(r"[a-zA-Z]{4}( [a-zA-Z]{4}){3}", password):
        password = password.replace(" ", "")
    return user, password, host


def prepare_message(path, now):
    """Return the message bytes with today's Date and a fresh Message-ID, CRLF line endings."""
    with path.open("rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    del msg["Date"]
    msg["Date"] = formatdate(now, localtime=True)
    # A fresh Message-ID keeps Gmail from treating a re-run as a duplicate.
    del msg["Message-ID"]
    msg["Message-ID"] = make_msgid(domain="hartwellfoods.example")
    return msg, msg.as_bytes(policy=policy.SMTP)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="Place the sample HR emails in the Gmail sandbox inbox (unread).")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the messages that would be loaded, without signing in")
    args = parser.parse_args()

    files = sorted(SAMPLE_DIR.glob("*.eml"))
    if not files:
        sys.exit(f"No .eml files found in {SAMPLE_DIR}")

    now = time.time()
    prepared = [(p, *prepare_message(p, now)) for p in files]

    if args.dry_run:
        print(f"Dry run: {len(prepared)} message(s) would be placed in {MAILBOX}, unread, dated today:")
        for p, msg, _ in prepared:
            print(f"  {p.name}: From {msg['From']} | Subject: {msg['Subject']}")
        return

    user, password, host = read_login()
    try:
        imap = imaplib.IMAP4_SSL(host, 993)
    except OSError as e:
        sys.exit(f"Could not connect to {host}: {e}")

    try:
        try:
            imap.login(user, password)
        except imaplib.IMAP4.error:
            # Deliberately not echoing anything that could contain the password.
            sys.exit("Sign-in failed. Check the address and app password in Agent-Email.txt, "
                     "and that IMAP is enabled for the account.")
        finally:
            password = None
        print(f"Signed in to {host}.")

        loaded = 0
        for p, msg, data in prepared:
            # Empty flags = no \Seen, so the message arrives unread. The internal date is today.
            status, resp = imap.append(MAILBOX, "", imaplib.Time2Internaldate(now), data)
            if status == "OK":
                loaded += 1
                print(f"  placed  {p.name}: {msg['Subject']}")
            else:
                print(f"  FAILED  {p.name}: {resp}")
        print(f"\nDone: {loaded} of {len(prepared)} message(s) placed in {MAILBOX} as unread. Nothing was sent.")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
