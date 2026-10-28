import secrets

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from tourism.models import StoredCredentialApiUser


class Command(BaseCommand):
    help = "Create an API username and password for the stored-credentials API."

    def handle(self, *args, **options):
        if StoredCredentialApiUser.objects.exists():
            raise CommandError(
                "A stored-credentials API user already exists. Rotate it through your deployment process."
            )
        username = f"cred_api_{secrets.token_hex(4)}"
        password = secrets.token_urlsafe(32)
        StoredCredentialApiUser.objects.create(
            username=username,
            password_hash=make_password(password),
        )
        self.stdout.write(self.style.SUCCESS("API credentials created. Save these values now; the password cannot be shown again."))
        self.stdout.write(f"Username: {username}")
        self.stdout.write(f"Password: {password}")
