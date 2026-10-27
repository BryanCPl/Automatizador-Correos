#!/usr/bin/env python3
"""Send personalized emails to the contacts listed in a CSV file.

Every send attempt is recorded in a history CSV (default: email_history.csv).
"""

import argparse
import csv
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLACEHOLDER_REGEX = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

HISTORY_FIELDS = ["timestamp", "status", "email", "name", "subject", "error"]


def render_template(template: str, values: dict[str, str]) -> str:
"""Replace {column_name} placeholders without changing unknown placeholders."""
normalized_values = {key.strip().lower(): value for key, value in values.items()}
return PLACEHOLDER_REGEX.sub(
lambda match: normalized_values.get(match.group(1).lower(), match.group(0)),
template,
)


def load_contacts(csv_path: Path) -> list[dict[str, str]]:
if not csv_path.is_file():
raise FileNotFoundError(f"Contacts CSV not found: {csv_path}")

with csv_path.open("r", encoding="utf-8-sig", newline="") as contacts_file:
reader = csv.DictReader(contacts_file)
if not reader.fieldnames or not any(
field.strip().lower() == "email" for field in reader.fieldnames if field
):
raise ValueError("The contacts CSV must have an 'email' column.")

contacts = [
{key: value or "" for key, value in row.items() if key is not None}
for row in reader
]

if not contacts:
raise ValueError(f"No contacts found in {csv_path}.")
return contacts


def get_recipient_name(row: dict[str, str]) -> str:
return next(
(
value.strip()
for key, value in row.items()
if key.strip().lower() in ("name", "first_name", "firstname")
and value.strip()
),
"",
)


# ---------------------------------------------------------------- history ----

def append_history(history_path: Path, status: str, email: str, name: str,
subject: str, error: str = "") -> None:
"""Append one entry to the history CSV (creates the file with header if needed)."""
try:
is_new = not history_path.is_file() or history_path.stat().st_size == 0
with history_path.open("a", encoding="utf-8", newline="") as history_file:
writer = csv.DictWriter(history_file, fieldnames=HISTORY_FIELDS)
if is_new:
writer.writeheader()
writer.writerow(
{
"timestamp": datetime.now().isoformat(timespec="seconds"),
"status": status,
"email": email,
"name": name,
"subject": subject,
"error": error,
}
)
except OSError as error_:
print(f"[WARN] Could not write history file: {error_}", file=sys.stderr)


def read_history(history_path: Path) -> list[dict[str, str]]:
if not history_path.is_file():
return []
with history_path.open("r", encoding="utf-8", newline="") as history_file:
return list(csv.DictReader(history_file))


def already_sent(history: list[dict[str, str]]) -> set[tuple[str, str]]:
"""(email, subject) pairs that were sent successfully before."""
return {
(entry["email"].lower(), entry["subject"])
for entry in history
if entry.get("status") == "SENT"
}


def show_history(history_path: Path, limit: int) -> int:
history = read_history(history_path)
if not history:
print(f"No history found in {history_path}.")
return 0

entries = history[-limit:] if limit > 0 else history
print(f"History ({len(entries)} of {len(history)} entries) - {history_path}")
for entry in entries:
line = (
f"{entry['timestamp']} | {entry['status']:<6} | "
f"{entry['email']} | {entry['subject']}"
)
if entry.get("error"):
line += f" | {entry['error']}"
print(line)

sent = sum(1 for e in history if e["status"] == "SENT")
failed = sum(1 for e in history if e["status"] == "FAILED")
print(f"Total: {sent} sent, {failed} failed.")
return 0


# ------------------------------------------------------------------- main ----

def main() -> int:
parser = argparse.ArgumentParser(
description="Send a personalized email to every valid address in a CSV file."
)
parser.add_argument(
"--csv",
type=Path,
default=Path(__file__).with_name("contacts.csv"),
help="CSV with an email column (default: contacts.csv beside this script)",
)
parser.add_argument(
"--subject",
default=os.getenv("EMAIL_SUBJECT"),
help="Email subject; supports {column} placeholders (or EMAIL_SUBJECT in .env)",
)
parser.add_argument(
"--message",
default=os.getenv("EMAIL_MESSAGE"),
help="Email body; supports {column} placeholders (or EMAIL_MESSAGE in .env)",
)
parser.add_argument(
"--history",
type=Path,
default=Path(
os.getenv("EMAIL_HISTORY", str(Path(__file__).with_name("email_history.csv")))
),
help="History CSV file (default: email_history.csv beside this script, or EMAIL_HISTORY in .env)",
)
parser.add_argument(
"--show-history",
action="store_true",
help="Show the sent-email history and exit",
)
parser.add_argument(
"--limit",
type=int,
default=20,
help="Entries to show with --show-history (0 = all, default: 20)",
)
parser.add_argument(
"--skip-sent",
action="store_true",
help="Skip contacts that already received this same subject (per the history)",
)
parser.add_argument(
"--dry-run",
action="store_true",
help="Preview recipients without connecting to SMTP or sending emails",
)
args = parser.parse_args()

if args.show_history:
return show_history(args.history, args.limit)

if not args.subject or not args.message:
parser.error("Provide --subject and --message or set EMAIL_SUBJECT and EMAIL_MESSAGE in .env.")

try:
contacts = load_contacts(args.csv)
except (OSError, ValueError) as error:
print(f"[ERROR] {error}", file=sys.stderr)
return 1

sender_email = os.getenv("SENDER_EMAIL") or os.getenv("EMAIL", "")
sender_password = os.getenv("SENDER_PASSWORD") or os.getenv("PASSWORD", "")
sender_name = os.getenv("SENDER_NAME", "")
smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")

try:
smtp_port = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
print("[ERROR] SMTP_PORT must be a valid port number.", file=sys.stderr)
return 1
if not 1 <= smtp_port <= 65535:
print("[ERROR] SMTP_PORT must be between 1 and 65535.", file=sys.stderr)
return 1

use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("true", "1", "yes")

previously_sent = already_sent(read_history(args.history)) if args.skip_sent else set()

valid_contacts = []
for row in contacts:
email_key = next((key for key in row if key.strip().lower() == "email"), None)
recipient_email = row.get(email_key, "").strip() if email_key else ""
if not EMAIL_REGEX.fullmatch(recipient_email):
print(f"[SKIP] Invalid email address: {recipient_email!r}")
if not args.dry_run:
append_history(
args.history, "SKIPPED", recipient_email,
get_recipient_name(row), "", "Invalid email address",
)
continue
row["email"] = recipient_email

if (recipient_email.lower(), render_template(args.subject, row)) in previously_sent:
print(f"[SKIP] Already sent before: {recipient_email}")
continue

valid_contacts.append(row)

if not valid_contacts:
print("[ERROR] No valid email addresses to send to.", file=sys.stderr)
return 1

if args.dry_run:
print(f"[DRY-RUN] Would send {len(valid_contacts)} email(s):")
for row in valid_contacts:
print(f" {row['email']} | {render_template(args.subject, row)}")
return 0

if not sender_email or not sender_password:
print(
"[ERROR] Set SENDER_EMAIL and SENDER_PASSWORD (or EMAIL and PASSWORD) in .env.",
file=sys.stderr,
)
return 1

context = ssl.create_default_context()
sent_count = 0
failed_count = 0
try:
smtp_connection = (
smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30, context=context)
if smtp_port == 465
else smtplib.SMTP(smtp_server, smtp_port, timeout=30)
)
with smtp_connection as smtp:
smtp.ehlo()
if use_tls and smtp_port != 465:
smtp.starttls(context=context)
smtp.ehlo()
smtp.login(sender_email, sender_password)

for row in valid_contacts:
recipient_email = row["email"]
recipient_name = get_recipient_name(row)
display_name = recipient_name or recipient_email
subject = render_template(args.subject, row)

message = EmailMessage()
message["Subject"] = subject
message["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
message["To"] = recipient_email
message.set_content(render_template(args.message, row))

try:
smtp.send_message(message)
except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError) as error:
# Problem with this recipient only: log it and keep going.
failed_count += 1
append_history(
args.history, "FAILED", recipient_email,
recipient_name, subject, str(error),
)
print(f"[FAILED] {display_name} <{recipient_email}>: {error}")
continue

sent_count += 1
append_history(args.history, "SENT", recipient_email, recipient_name, subject)
print(f"[SENT] {display_name} <{recipient_email}>")

except (OSError, smtplib.SMTPException) as error:
print(
f"[ERROR] SMTP failed after {sent_count} email(s): {error}",
file=sys.stderr,
)
return 1

print(f"Completed: {sent_count} email(s) sent, {failed_count} failed.")
print(f"History saved in: {args.history}")
return 0


if __name__ == "__main__":
raise SystemExit(main())
