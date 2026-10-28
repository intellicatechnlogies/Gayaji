import imaplib
import re
import smtplib
import sqlite3
import tempfile
from contextlib import closing
from email import message_from_bytes
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any

from django.conf import settings
from cryptography.fernet import InvalidToken
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError

from tourism.credential_vault import decrypt_credential
from tourism.models import StoredCredential

BACKUP_EMAIL = "raumishji@gmail.com"
BACKUP_SUBJECT = "Gaya Ji - DB Backup"
MAILBOXES = ("INBOX",)
IMAP_HOST = "imap.gmail.com"
RETAIN_PER_MAILBOX = 2


def stored_email_credential(name: str) -> str:
    credential = StoredCredential.objects.filter(
        service__iexact="Email",
        name__iexact=name,
    ).first()
    if credential is None:
        raise CommandError(f"Missing Email credential: {name}.")
    try:
        value = decrypt_credential(credential.encrypted_secret)
    except (InvalidToken, UnicodeError) as exc:
        raise CommandError(
            f"Email credential {name} cannot be decrypted. Save it again through the credentials API."
        ) from exc
    if not value.strip():
        raise CommandError(f"Email credential {name} is empty.")
    return value.strip()


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

    matching_uids = []
    for uid in (results or [b""])[0].split():
        status, response = connection.uid(
            "fetch",
            uid,
            "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO)])",
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
            matching_uids.append(uid)

    matching_uids.sort(key=lambda uid: int(uid), reverse=True)
    old_uids = matching_uids[RETAIN_PER_MAILBOX:]
    for uid in old_uids:
        status, _ = connection.uid("store", uid, "+FLAGS.SILENT", r"(\Deleted)")
        if status != "OK":
            raise CommandError(f"Could not mark an old backup for deletion in {mailbox}.")
    if old_uids:
        status, _ = connection.expunge()
        if status != "OK":
            raise CommandError(f"Could not permanently delete old backups from {mailbox}.")
    return len(old_uids)


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
    help = "Email a SQLite database backup and retain the two newest copies in Gmail Inbox and Sent."

    def handle(self, *args, **options):
        host = stored_email_credential("SMTP_Server")
        port_value = stored_email_credential("Port")
        app_password = stored_email_credential("App_Password").replace(" ", "")
        try:
            port = int(port_value)
        except ValueError as exc:
            raise CommandError("Email credential Port must be a valid port number.") from exc
        if not 1 <= port <= 65535:
            raise CommandError("Email credential Port must be between 1 and 65535.")

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

        use_ssl = port == 465
        connection = get_connection(
            host=host,
            port=port,
            username=BACKUP_EMAIL,
            password=app_password,
            use_tls=port == 587,
            use_ssl=use_ssl,
            timeout=20,
        )
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
