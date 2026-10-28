import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["GAYAJI_WEB_PROCESS"] = "1"

application = get_wsgi_application()
