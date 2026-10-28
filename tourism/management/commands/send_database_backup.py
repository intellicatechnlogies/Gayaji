import imaplib
import re
import smtplib
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError

from tourism.email_utils import EMAIL_ADDRESS, get_email_connection, stored_email_credential

BACKUP_EMAIL = EMAIL_ADDRESS
BACKUP_SUBJECT = "Gaya Ji - DB Backup"
MAILBOXES = ("INBOX",)
IMAP_HOST = "imap.gmail.com"
BACKUP_RETENTION = timedelta(hours=48)


def database_backup(database_path: Path, backup_path: Path) -> None:
    if not database_path.is_file():
        raise CommandError(f"SQLite database file not found: {database_path}.")
    try:
        with closing(sqlite3.connect(database_path)) as source, closing(
            sqlite3.connect(backup_path)
        ) as destination:
            source.backup(destination)
    except sqlite3.Error as exc:
        raise CommandError("Could not create a consistent SQLite database backup.") from exc


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (LookupError, UnicodeError, ValueError):
        return value.strip()


def _is_backup_for_account(header: Any, address: str) -> bool:
    from email.utils import getaddresses

    subject = _decode_header(header.get("Subject"))
    senders = {
        email.casefold()
        for _name, email in getaddresses([header.get("From", "")])
    }
    recipients = {
        email.casefold()
        for _name, email in getaddresses([header.get("To", "")])
    }
    return (
        subject == BACKUP_SUBJECT
        and address.casefold() in senders
        and address.casefold() in recipients
    )


def _is_expired_backup(internal_date: str, now: datetime | None = None) -> bool:
    try:
        received_at = datetime.strptime(
            internal_date,
            "%d-%b-%Y %H:%M:%S %z",
        ).astimezone(timezone.utc)
    except ValueError as exc:
        raise CommandError("Could not parse a backup email's Gmail receive date.") from exc
    current_time = now or datetime.now(timezone.utc)
    return received_at < current_time - BACKUP_RETENTION


def _sent_mailbox(connection: imaplib.IMAP4_SSL) -> str:
    status, mailboxes = connection.list()
    if status != "OK":
        raise CommandError("Could not list Gmail mailboxes for backup retention.")
    for mailbox in mailboxes or []:
        if not isinstance(mailbox, bytes):
            continue
        match = re.match(rb"\(([^)]*)\)\s+(?:\"[^\"]*\"|NIL)\s+(.+)$", mailbox)
        if match and b"\\sent" in match.group(1).lower():
            name = match.group(2).strip()
            if name.startswith(b'"') and name.endswith(b'"'):
                name = name[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
            return name.decode("utf-8")
    raise CommandError("Gmail Sent mailbox was not found. Check Gmail IMAP settings.")


def _prune_mailbox(connection: imaplib.IMAP4_SSL, mailbox: str, address: str) -> int:
    if re.search(r'[\s(){}\\"]', mailbox):
        escaped_mailbox = mailbox.replace("\\", "\\\\").replace('"', '\\"')
        mailbox_argument = f'"{escaped_mailbox}"'
    else:
        mailbox_argument = mailbox
    status, _ = connection.select(mailbox_argument, readonly=False)
    if status != "OK":
        raise CommandError(f"Could not open Gmail mailbox {mailbox}.")
    status, results = connection.uid("search", None, "SUBJECT", f'"{BACKUP_SUBJECT}"')
    if status != "OK":
        raise CommandError(f"Could not search Gmail mailbox {mailbox}.")

    expired_uids = []
    for uid in (results or [b""])[0].split():
        status, response = connection.uid(
            "fetch",
            uid,
            "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO)])",
        )
        if status != "OK":
            raise CommandError(f"Could not inspect a message in Gmail mailbox {mailbox}.")
        raw_header = next(
            (
                part[1]
                for part in response or []
                if isinstance(part, tuple) and isinstance(part[1], bytes)
            ),
            b"",
        )
        header = message_from_bytes(raw_header)
        if _is_backup_for_account(header, address):
            metadata = next(
                (
                    part[0]
                    for part in response or []
                    if isinstance(part, tuple) and isinstance(part[0], bytes)
                ),
                b"",
            )
            internal_date_match = re.search(rb'INTERNALDATE "([^"]+)"', metadata)
            if internal_date_match is None:
                raise CommandError(
                    f"Could not read the receive date of a backup in Gmail mailbox {mailbox}."
                )
            internal_date = internal_date_match.group(1).decode("ascii")
            if _is_expired_backup(internal_date):
                expired_uids.append(uid)

    for uid in expired_uids:
        status, _ = connection.uid("store", uid, "+FLAGS.SILENT", r"(\Deleted)")
        if status != "OK":
            raise CommandError(f"Could not mark an old backup for deletion in {mailbox}.")
    if expired_uids:
        status, _ = connection.expunge()
        if status != "OK":
            raise CommandError(f"Could not permanently delete old backups from {mailbox}.")
    return len(expired_uids)


def prune_old_backups(address: str, app_password: str) -> int:
    connection = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        status, _ = connection.login(address, app_password)
        if status != "OK":
            raise CommandError("Gmail IMAP login failed; check the saved app password.")
        sent_mailbox = _sent_mailbox(connection)
        deleted = sum(
            _prune_mailbox(connection, mailbox, address)
            for mailbox in (*MAILBOXES, sent_mailbox)
        )
        return deleted
    except (imaplib.IMAP4.error, OSError) as exc:
        raise CommandError("Could not connect to Gmail IMAP for backup retention.") from exc
    finally:
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


class Command(BaseCommand):
    help = "Email a SQLite database backup and retain matching messages from the last 48 hours."

    def handle(self, *args, **options):
        app_password = stored_email_credential("App_Password").replace(" ", "")

        database_path = Path(settings.DATABASES["default"]["NAME"])
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("Database backup email currently supports SQLite only.")

        with tempfile.TemporaryDirectory(prefix="gayaji-db-backup-") as temp_dir:
            backup_path = Path(temp_dir) / "bodh_gaya_tourism.db"
            database_backup(database_path, backup_path)
            try:
                backup_data = backup_path.read_bytes()
            except OSError as exc:
                raise CommandError("Could not read the generated database backup.") from exc

        connection = get_email_connection()
        message = EmailMessage(
            subject=BACKUP_SUBJECT,
            body="Automated five-minute backup of the Gaya Ji SQLite database.",
            from_email=BACKUP_EMAIL,
            to=[BACKUP_EMAIL],
            connection=connection,
        )
        message.attach(
            "bodh_gaya_tourism.db",
            backup_data,
            "application/vnd.sqlite3",
        )
        try:
            sent_count = message.send()
        except (OSError, ValueError, smtplib.SMTPException) as exc:
            raise CommandError("Could not send the database backup email through SMTP.") from exc
        finally:
            connection.close()
        if sent_count != 1:
            raise CommandError("SMTP did not confirm sending the database backup email.")

        deleted_count = prune_old_backups(BACKUP_EMAIL, app_password)
        self.stdout.write(
            self.style.SUCCESS(
                f"Database backup sent to {BACKUP_EMAIL}; permanently removed {deleted_count} older backup message(s)."
            )
        )
