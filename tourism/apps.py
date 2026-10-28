import os
import sys

from django.apps import AppConfig


class TourismConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "tourism"

    def ready(self):
        should_start = os.environ.get("GAYAJI_WEB_PROCESS") == "1"
        is_runserver = len(sys.argv) > 1 and sys.argv[1] == "runserver"
        if is_runserver:
            is_autoreloader_child = os.environ.get("RUN_MAIN") == "true"
            is_without_autoreloader = "--noreload" in sys.argv
            should_start = is_autoreloader_child or is_without_autoreloader
        elif sys.argv and sys.argv[0].lower().endswith("manage.py"):
            should_start = False

        if should_start:
            from .backup_scheduler import start_backup_scheduler

            start_backup_scheduler()
