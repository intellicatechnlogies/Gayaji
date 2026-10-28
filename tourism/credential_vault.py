import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def credential_cipher() -> Fernet:
    key_material = hashlib.sha256(
        b"stored-credentials-v1\0" + settings.SECRET_KEY.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def encrypt_credential(secret: str) -> str:
    return credential_cipher().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_credential(encrypted_secret: str) -> str:
    return credential_cipher().decrypt(encrypted_secret.encode("ascii")).decode("utf-8")
