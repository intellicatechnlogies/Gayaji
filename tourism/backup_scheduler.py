import logging
import threading

from django.core.management import call_command
from django.core.management.base import CommandError

BACKUP_INTERVAL_SECONDS = 60 * 60
logger = logging.getLogger(__name__)
_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None


def run_backup_scheduler(stop_event: threading.Event | None = None) -> None:
    event = stop_event or threading.Event()
    while not event.is_set():
        try:
            call_command("send_database_backup")
        except CommandError:
            logger.exception("Scheduled database backup failed.")
        if event.wait(BACKUP_INTERVAL_SECONDS):
            return


def start_backup_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return
        _scheduler_thread = threading.Thread(
            target=run_backup_scheduler,
            name="gayaji-database-backup",
            daemon=True,
        )
        _scheduler_thread.start()
