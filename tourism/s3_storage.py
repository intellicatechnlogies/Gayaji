from io import BytesIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.fernet import InvalidToken
from PIL import Image, UnidentifiedImageError

from .credential_vault import decrypt_credential
from .models import StoredCredential

MAX_PLACE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PLACE_IMAGE_PIXELS = 40_000_000
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class S3StorageError(Exception):
    pass


def _stored_aws_value(*names: str) -> str:
    credential = StoredCredential.objects.filter(
        service__iexact="AWS",
        name__in=names,
    ).first()
    if credential is None:
        credential = next(
            (
                item
                for item in StoredCredential.objects.filter(service__iexact="AWS")
                if item.name.casefold() in {name.casefold() for name in names}
            ),
            None,
        )
    if credential is None:
        raise S3StorageError(f"Missing AWS credential: {names[0]}.")
    try:
        value = decrypt_credential(credential.encrypted_secret)
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise S3StorageError(
            f"The stored AWS credential {names[0]} cannot be decrypted. Save it again through the credentials API."
        ) from exc
    if not value.strip():
        raise S3StorageError(f"The stored AWS credential {names[0]} is empty.")
    return value


def get_s3_client():
    access_key = _stored_aws_value("Acces_key", "Access_key")
    secret_key = _stored_aws_value("Secret_access_key")
    region = _stored_aws_value("Region")
    bucket = _stored_aws_value("S3bucket")
    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(s3={"addressing_style": "virtual"}),
        )
    except (BotoCoreError, ValueError) as exc:
        raise S3StorageError("Could not configure the S3 client from the saved AWS credentials.") from exc
    return client, bucket


def prepare_place_image(uploaded_file) -> tuple[bytes, str]:
    if uploaded_file.size <= 0 or uploaded_file.size > MAX_PLACE_IMAGE_BYTES:
        raise ValueError("Choose an image smaller than 10 MB.")
    try:
        with Image.open(uploaded_file) as image:
            if image.format not in ALLOWED_IMAGE_FORMATS:
                raise ValueError("Upload a JPEG, PNG, WEBP, or GIF image.")
            if image.width * image.height > MAX_PLACE_IMAGE_PIXELS:
                raise ValueError("The uploaded image dimensions are too large.")
            content_type = Image.MIME[image.format]
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The uploaded file is not a valid supported image.") from exc
    uploaded_file.seek(0)
    return uploaded_file.read(), content_type


def upload_place_image(place_id: int, content: bytes, content_type: str) -> None:
    client, bucket = get_s3_client()
    try:
        client.put_object(
            Bucket=bucket,
            Key=f"places/{place_id}",
            Body=BytesIO(content),
            ContentType=content_type,
            CacheControl="public, max-age=3600",
        )
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError("Could not upload the destination image to S3.") from exc


def get_place_image_url(place_id: int) -> str | None:
    client, bucket = get_s3_client()
    try:
        client.head_object(Bucket=bucket, Key=f"places/{place_id}")
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": f"places/{place_id}"},
            ExpiresIn=3600,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise S3StorageError("Could not create a temporary S3 image link.") from exc
    except (BotoCoreError, ValueError) as exc:
        raise S3StorageError("Could not create a temporary S3 image link.") from exc


def delete_place_image(place_id: int) -> None:
    client, bucket = get_s3_client()
    try:
        client.delete_object(Bucket=bucket, Key=f"places/{place_id}")
    except (BotoCoreError, ClientError) as exc:
        raise S3StorageError("Could not remove the destination image from S3.") from exc
