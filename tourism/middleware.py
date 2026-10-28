import ipaddress
from urllib.parse import urlsplit

from .backup_scheduler import start_backup_scheduler


def _is_local_host(host: str) -> bool:
    hostname = (urlsplit(f"//{host}").hostname or "").rstrip(".").casefold()
    if hostname in {"localhost", "testserver"} or hostname.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


class BackupSchedulerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _is_local_host(request.get_host()):
            start_backup_scheduler()
        return self.get_response(request)
