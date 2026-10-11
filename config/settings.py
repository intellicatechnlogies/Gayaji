from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

# Update these values here for the target deployment.
SECRET_KEY = "local-development-only-change-before-deploying"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "tourism.apps.TourismConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "bodh_gaya_tourism.db",
        "OPTIONS": {"timeout": 20},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = False

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "app" / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

EMAIL_HOST = ""
EMAIL_PORT = 587
EMAIL_USE_SSL = False
EMAIL_USE_TLS = not EMAIL_USE_SSL
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
ALERT_EMAIL = ""
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER or ALERT_EMAIL
EMAIL_TIMEOUT = 12
