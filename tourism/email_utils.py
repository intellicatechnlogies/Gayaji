import logging
import smtplib
import threading

from cryptography.fernet import InvalidToken
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from .credential_vault import decrypt_credential
from .models import NotificationOutbox, StoredCredential

EMAIL_ADDRESS = "raumishji@gmail.com"
logger = logging.getLogger(__name__)


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


def get_email_connection():
    host = stored_email_credential("SMTP_Server")
    port_value = stored_email_credential("Port")
    app_password = stored_email_credential("App_Password").replace(" ", "")
    try:
        port = int(port_value)
    except ValueError as exc:
        raise CommandError("Email credential Port must be a valid port number.") from exc
    if not 1 <= port <= 65535:
        raise CommandError("Email credential Port must be between 1 and 65535.")

    return get_connection(
        host=host,
        port=port,
        username=EMAIL_ADDRESS,
        password=app_password,
        use_tls=port == 587,
        use_ssl=port == 465,
        timeout=20,
    )


def send_notification_email(subject: str, body: str) -> None:
    connection = get_email_connection()
    try:
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=EMAIL_ADDRESS,
            to=[EMAIL_ADDRESS],
            connection=connection,
        )
        sent_count = message.send()
    except (OSError, ValueError, smtplib.SMTPException) as exc:
        raise CommandError("Could not send the notification email through SMTP.") from exc
    finally:
        connection.close()
    if sent_count != 1:
        raise CommandError("SMTP did not confirm sending the notification email.")


def _deliver_notification(outbox_id: int) -> None:
    claimed = NotificationOutbox.objects.filter(
        pk=outbox_id,
        status=NotificationOutbox.Status.QUEUED,
    ).update(status=NotificationOutbox.Status.SENDING)
    if not claimed:
        return
    notification = NotificationOutbox.objects.get(pk=outbox_id)
    try:
        send_notification_email(notification.subject, notification.body)
    except CommandError as exc:
        logger.exception("Could not deliver queued notification %s.", outbox_id)
        NotificationOutbox.objects.filter(pk=outbox_id).update(
            status=NotificationOutbox.Status.FAILED,
            error=str(exc),
        )
        return
    NotificationOutbox.objects.filter(pk=outbox_id).update(
        status=NotificationOutbox.Status.SENT,
        error="",
        sent_at=timezone.now(),
    )


def queue_notification_email(subject: str, body: str) -> NotificationOutbox:
    notification = NotificationOutbox.objects.create(subject=subject, body=body)
    transaction.on_commit(
        lambda: threading.Thread(
            target=_deliver_notification,
            args=(notification.pk,),
            name=f"email-notification-{notification.pk}",
            daemon=True,
        ).start()
    )
    return notification
