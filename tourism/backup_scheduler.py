import logging
import os
import threading
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

BACKUP_INTERVAL_SECONDS = 60 * 60
PROCESS_LOCK_RETRY_SECONDS = 5
logger = logging.getLogger(__name__)
_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None


def _try_acquire_process_lock(lock_path: Path):
    lock_file = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def _run_as_single_scheduler(event: threading.Event) -> None:
    database_path = Path(settings.DATABASES["default"]["NAME"]).resolve()
    lock_path = database_path.with_name(f"{database_path.name}.backup-scheduler.lock")
    while not event.is_set():
        try:
            lock_file = _try_acquire_process_lock(lock_path)
        except OSError:
            logger.exception("Could not open the database backup scheduler lock file.")
            return
        if lock_file is None:
            if event.wait(PROCESS_LOCK_RETRY_SECONDS):
                return
            continue
        try:
            run_backup_scheduler(event)
            return
        finally:
            lock_file.close()


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
            target=_run_as_single_scheduler,
            args=(threading.Event(),),
            name="gayaji-database-backup",
            daemon=True,
        )
        _scheduler_thread.start()
