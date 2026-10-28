import os

from django.apps import AppConfig


class TourismConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "tourism"

    def ready(self):
        should_start = os.environ.get("GAYAJI_WEB_PROCESS") == "1"
        if should_start:
            from .backup_scheduler import start_backup_scheduler

            start_backup_scheduler()
