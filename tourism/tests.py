import base64
import json
import sqlite3
import tempfile
from contextlib import closing
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import RequestFactory, TestCase, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from PIL import Image

from .models import (
    AdminAccount,
    Booking,
    CityPincode,
    Guide,
    GuideLanguage,
    Hotel,
    HotelLocation,
    Inquiry,
    NotificationOutbox,
    Place,
    PlanningRequest,
    Restaurant,
    StoredCredential,
    StoredCredentialApiUser,
    Van,
)
from .credential_vault import decrypt_credential, encrypt_credential
from .management.commands.send_database_backup import (
    BACKUP_EMAIL,
    BACKUP_SUBJECT,
    database_backup,
    _is_expired_backup,
    prune_old_backups,
)
from .backup_scheduler import (
    BACKUP_INTERVAL_SECONDS,
    _try_acquire_process_lock,
    run_backup_scheduler,
)
from .views import hash_password, send_booking_notification, verify_password


class BootstrapDataCommandTests(TestCase):
    def test_bootstrap_prompts_for_admin_and_stores_password_hash(self):
        password = "Gayaji"
        output = StringIO()
        with (
            patch("builtins.input", return_value="  FirstAdmin  "),
            patch("getpass.getpass", side_effect=[password, password]),
        ):
            call_command("bootstrap_data", stdout=output)

        admin = AdminAccount.objects.get(username="firstadmin")
        self.assertNotEqual(admin.password_hash, password)
        self.assertTrue(verify_password(password, admin.password_hash))
        self.assertEqual(Place.objects.count(), 8)
        self.assertIn("Created initial admin account 'firstadmin'.", output.getvalue())

    def test_bootstrap_rejects_mismatched_admin_passwords(self):
        with (
            patch("builtins.input", return_value="admin"),
            patch("getpass.getpass", side_effect=["first-password-long", "different-password-long"]),
            self.assertRaises(CommandError),
        ):
            call_command("bootstrap_data", stdout=StringIO())

        self.assertFalse(AdminAccount.objects.exists())


class TourismApiTests(TestCase):
    def setUp(self):
        self.admin = AdminAccount.objects.create(
            username="admin",
            password_hash=hash_password("test-password-long-enough"),
        )

    def test_database_backup_uses_sqlite_online_backup_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.db"
            backup_path = Path(temp_dir) / "backup.db"
            with closing(sqlite3.connect(source_path)) as source:
                source.execute("CREATE TABLE backup_test (value TEXT)")
                source.execute("INSERT INTO backup_test VALUES ('saved')")
                source.commit()

            database_backup(source_path, backup_path)

            with closing(sqlite3.connect(backup_path)) as backup:
                self.assertEqual(backup.execute("SELECT value FROM backup_test").fetchone(), ("saved",))

    def test_database_backup_command_sends_attachment_and_runs_retention(self):
        for name, value in {
            "SMTP_Server": "smtp.gmail.com",
            "Port": "587",
            "App_Password": "test app password",
        }.items():
            StoredCredential.objects.create(
                service="Email",
                name=name,
                encrypted_secret=encrypt_credential(value),
            )

        class FakeMailConnection:
            def __init__(self):
                self.messages = []
                self.closed = False

            def send_messages(self, messages):
                self.messages.extend(messages)
                return len(messages)

            def close(self):
                self.closed = True

        fake_connection = FakeMailConnection()
        with (
            patch("tourism.email_utils.get_connection", return_value=fake_connection) as get_connection,
            patch(
                "tourism.management.commands.send_database_backup.database_backup",
                side_effect=lambda _source, destination: destination.write_bytes(b"sqlite backup"),
            ) as make_backup,
            patch("tourism.management.commands.send_database_backup.prune_old_backups", return_value=2) as prune,
        ):
            call_command("send_database_backup", stdout=StringIO())
        make_backup.assert_called_once()

        get_connection.assert_called_once_with(
            host="smtp.gmail.com",
            port=587,
            username=BACKUP_EMAIL,
            password="testapppassword",
            use_tls=True,
            use_ssl=False,
            timeout=20,
        )
        self.assertTrue(fake_connection.closed)
        self.assertEqual(len(fake_connection.messages), 1)
        message = fake_connection.messages[0]
        self.assertEqual(message.subject, BACKUP_SUBJECT)
        self.assertEqual(message.from_email, BACKUP_EMAIL)
        self.assertEqual(message.to, [BACKUP_EMAIL])
        self.assertEqual(message.attachments[0].filename, "bodh_gaya_tourism.db")
        prune.assert_called_once_with(BACKUP_EMAIL, "testapppassword")

    def test_booking_notification_uses_the_backup_smtp_credentials(self):
        for name, value in {
            "SMTP_Server": "smtp.gmail.com",
            "Port": "587",
            "App_Password": "test app password",
        }.items():
            StoredCredential.objects.create(
                service="Email",
                name=name,
                encrypted_secret=encrypt_credential(value),
            )

        class FakeMailConnection:
            def __init__(self):
                self.messages = []
                self.closed = False

            def send_messages(self, messages):
                self.messages.extend(messages)
                return len(messages)

            def close(self):
                self.closed = True

        fake_connection = FakeMailConnection()
        with patch("tourism.email_utils.get_connection", return_value=fake_connection) as get_connection:
            send_booking_notification(
                {
                    "booking_type": "guided",
                    "name": "Traveler",
                    "email": "traveler@example.com",
                    "phone": "+911234567890",
                    "destination": "Gaya, Rajgir",
                    "travel_date": "2026-11-20",
                    "guests": 2,
                    "notes": "Morning visit",
                }
            )

        get_connection.assert_called_once_with(
            host="smtp.gmail.com",
            port=587,
            username=BACKUP_EMAIL,
            password="testapppassword",
            use_tls=True,
            use_ssl=False,
            timeout=20,
        )
        self.assertTrue(fake_connection.closed)
        self.assertEqual(len(fake_connection.messages), 1)
        email = fake_connection.messages[0]
        self.assertEqual(email.to, [BACKUP_EMAIL])
        self.assertIn("Destination: Gaya, Rajgir", email.body)
        self.assertIn("Morning visit", email.body)

    def test_backup_retention_keeps_matching_messages_from_last_48_hours(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        def received(hours_ago):
            return (now - timedelta(hours=hours_ago)).strftime("%d-%b-%Y %H:%M:%S %z")

        class FakeImap:
            def __init__(self):
                self.selected_mailbox = ""
                self.mailboxes = {
                    "INBOX": {
                        b"1": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(49)),
                        b"2": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(47)),
                        b"3": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(1)),
                        b"4": ("Other subject", BACKUP_EMAIL, BACKUP_EMAIL, received(72)),
                        b"5": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(24)),
                    },
                    "[Gmail]/Sent Mail": {
                        b"1": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(50)),
                        b"2": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(24)),
                        b"3": (BACKUP_SUBJECT, BACKUP_EMAIL, BACKUP_EMAIL, received(47)),
                    },
                }
                self.deleted = {}

            def login(self, _username, _password):
                return "OK", []

            def list(self):
                return "OK", [b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']

            def select(self, mailbox, readonly=False):
                self.selected_mailbox = mailbox.strip('"')
                return ("OK" if not readonly else "NO"), []

            def uid(self, operation, *args):
                mailbox = self.mailboxes[self.selected_mailbox]
                if operation == "search":
                    return "OK", [b" ".join(mailbox)]
                if operation == "fetch":
                    subject, sender, recipient, internal_date = mailbox[args[0]]
                    headers = (
                        "\r\n".join(
                            (
                                f"Subject: {subject}",
                                f"From: {sender}",
                                f"To: {recipient}",
                                "",
                                "",
                            )
                        )
                    ).encode()
                    metadata = f'INTERNALDATE "{internal_date}"'.encode()
                    return "OK", [(metadata, headers)]
                if operation == "store":
                    self.deleted.setdefault(self.selected_mailbox, []).append(args[0])
                    return "OK", []
                raise AssertionError(f"Unexpected IMAP operation {operation}")

            def expunge(self):
                for uid in self.deleted.get(self.selected_mailbox, []):
                    self.mailboxes[self.selected_mailbox].pop(uid)
                return "OK", []

            def logout(self):
                return "BYE", []

        fake_imap = FakeImap()
        with patch("tourism.management.commands.send_database_backup.imaplib.IMAP4_SSL", return_value=fake_imap):
            deleted = prune_old_backups(BACKUP_EMAIL, "app-password")

        self.assertEqual(deleted, 2)
        self.assertEqual(fake_imap.deleted["INBOX"], [b"1"])
        self.assertEqual(fake_imap.deleted["[Gmail]/Sent Mail"], [b"1"])
        self.assertEqual(len(fake_imap.mailboxes["INBOX"]), 4)
        self.assertEqual(len(fake_imap.mailboxes["[Gmail]/Sent Mail"]), 2)

    def test_backup_retention_expires_only_messages_older_than_48_hours(self):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        exactly_48_hours_old = (now - timedelta(hours=48)).strftime(
            "%d-%b-%Y %H:%M:%S %z"
        )
        older_than_48_hours = (now - timedelta(hours=48, seconds=1)).strftime(
            "%d-%b-%Y %H:%M:%S %z"
        )

        self.assertFalse(_is_expired_backup(exactly_48_hours_old, now))
        self.assertTrue(_is_expired_backup(older_than_48_hours, now))

    def test_background_scheduler_sends_backup_and_waits_five_minutes(self):
        stop_event = type(
            "StopAfterInterval",
            (),
            {"is_set": lambda self: False, "wait": lambda self, interval: interval == BACKUP_INTERVAL_SECONDS},
        )()
        with patch("tourism.backup_scheduler.call_command") as send_backup:
            run_backup_scheduler(stop_event)

        send_backup.assert_called_once_with("send_database_backup")
        self.assertEqual(BACKUP_INTERVAL_SECONDS, 21600)

    def test_backup_scheduler_process_lock_allows_only_one_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "scheduler.lock"
            first_lock = _try_acquire_process_lock(lock_path)
            self.assertIsNotNone(first_lock)
            try:
                self.assertIsNone(_try_acquire_process_lock(lock_path))
            finally:
                first_lock.close()

            second_lock = _try_acquire_process_lock(lock_path)
            self.assertIsNotNone(second_lock)
            second_lock.close()

    def test_backup_scheduler_starts_only_for_nonlocal_request_hosts(self):
        from tourism.middleware import BackupSchedulerMiddleware

        cases = (
            ("localhost:8000", False),
            ("127.0.0.1:8000", False),
            ("[::1]:8000", False),
            ("192.168.1.20:8000", False),
            ("testserver", False),
            ("gayaji.example.com", True),
        )
        for host, should_start in cases:
            with self.subTest(host=host):
                request = RequestFactory().get("/", HTTP_HOST=host)
                middleware = BackupSchedulerMiddleware(lambda _request: None)
                with patch("tourism.middleware.start_backup_scheduler") as start_scheduler:
                    middleware(request)
                self.assertEqual(start_scheduler.called, should_start)

    def test_collected_static_assets_are_served_when_debug_is_disabled(self):
        response = self.client.get("/static/styles.css")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ".hero{")

    def test_homepage_uses_django_template_and_renders_database_destinations(self):
        Place.objects.create(
            name="Template destination",
            description="A sufficiently detailed place description for the rendered page.",
            region="Nalanda",
            category="Heritage",
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tourism/home.html")
        self.assertContains(response, "Template destination")
        self.assertContains(response, 'id="admin-panel"')
        self.assertContains(response, 'id="booking-backdrop"')
        self.assertContains(response, '/static/site.js?v=van-charge-ranges-1')
        self.assertNotContains(response, "Tempo Traveller")
        self.assertContains(response, 'data-admin-tab="search">Search &amp; Filter</button>')
        self.assertContains(response, 'data-admin-tab="places">Manage Places</button>')
        self.assertContains(response, 'data-admin-tab="hotels">Manage Hotels</button>')
        self.assertContains(response, 'data-admin-tab="restaurants">Manage Restaurants</button>')
        self.assertContains(response, 'data-admin-tab="vans">Manage Vans</button>')
        self.assertContains(response, 'data-admin-tab="guides">Manage Guides</button>')
        self.assertContains(response, 'data-admin-tab="planning">Planning Requests</button>')
        self.assertContains(response, 'id="planning-request-table"')
        self.assertContains(response, 'id="planning-request-form"')
        self.assertNotContains(response, 'data-admin-tab="credentials"')
        self.assertNotContains(response, 'id="admin-credential-form"')
        self.assertContains(response, 'data-admin-section="search"')
        self.assertContains(response, 'id="place-region" name="region" required')
        self.assertContains(response, 'id="place-category" name="category" required')
        self.assertContains(response, 'id="place-image" name="image" type="file"')
        self.assertContains(response, 'id="place-image" name="image" type="file" accept="image/jpeg,image/png,image/webp,image/gif" required')
        self.assertContains(response, 'id="place-description" name="description" required')
        self.assertEqual(response.content.count(b'class="required-fields-note"'), 5)
        self.assertContains(response, 'data-listing-form="hotels"')
        self.assertContains(response, 'id="hotel-website" name="website" type="url"')
        self.assertNotContains(response, 'id="hotel-website" name="website" type="url" maxlength="500" required')
        self.assertContains(response, '<select id="hotel-stars" name="star_rating" required>')
        self.assertContains(response, 'value="7">7 stars</option>')
        self.assertContains(response, 'data-listing-form="restaurants"')
        self.assertContains(response, 'data-listing-form="vans"')
        self.assertContains(response, 'data-listing-form="guides"')
        self.assertContains(response, 'data-listing-search="hotels"')
        self.assertContains(response, 'data-overall-search-controls hidden')
        self.assertContains(response, 'data-listing-search="restaurants"')
        self.assertContains(response, 'data-listing-search="vans"')
        self.assertContains(response, 'data-listing-search="guides"')
        self.assertContains(response, 'data-overall-location-search')
        self.assertContains(response, 'data-overall-search-type="hotels" checked')
        self.assertContains(response, 'data-overall-search-type="restaurants" checked')
        self.assertContains(response, 'data-overall-search-type="vans" checked')
        self.assertContains(response, 'data-overall-search-type="guides" checked')
        self.assertContains(response, 'data-overall-filter="hotel-rating"')
        self.assertContains(response, 'data-overall-filter="hotel-ac"')
        self.assertContains(response, 'data-overall-filter="hotel-price-range"')
        self.assertContains(response, 'data-overall-filter="restaurant-food"')
        self.assertContains(response, 'data-overall-filter="restaurant-price"')
        self.assertContains(response, 'data-overall-filter="van-type"')
        self.assertContains(response, 'data-overall-filter="van-min-daily-charge"')
        self.assertContains(response, 'data-overall-filter="van-max-daily-charge"')
        self.assertContains(response, 'data-overall-filter="van-min-per-km-charge"')
        self.assertContains(response, 'data-overall-filter="van-max-per-km-charge"')
        self.assertContains(response, 'data-guide-search-languages')
        self.assertContains(response, 'data-overall-filter="guide-min-price"')
        self.assertContains(response, 'data-overall-filter="guide-max-price"')
        self.assertContains(response, 'data-overall-location-results')
        self.assertContains(response, 'value="Hindi" data-guide-language')
        self.assertContains(response, 'value="English" data-guide-language')
        self.assertContains(response, 'value="Pali" data-guide-language')
        self.assertContains(response, 'value="Tibetan" data-guide-language')
        self.assertContains(response, 'data-guide-language-other')
        self.assertContains(response, 'class="booking-destination-dropdown"')
        self.assertEqual(response.content.count(b'name="destination" value='), 4)
        self.assertContains(response, 'name="booking_type" value="complete-trip"')
        self.assertEqual(response.content.count(b'name="booking_type" value='), 4)
        self.assertEqual(response.content.count(b'name="arrangements" value='), 5)

    def test_static_assets_are_discoverable_for_collectstatic(self):
        self.assertIsNotNone(finders.find("styles.css"))
        self.assertIsNotNone(finders.find("site.js"))

    def test_whitenoise_serves_static_assets_without_collectstatic_when_debug_is_disabled(self):
        from whitenoise.middleware import WhiteNoiseMiddleware

        with tempfile.TemporaryDirectory() as static_root:
            with override_settings(
                DEBUG=False,
                STATIC_ROOT=static_root,
                WHITENOISE_USE_FINDERS=True,
                WHITENOISE_AUTOREFRESH=False,
            ):
                middleware = WhiteNoiseMiddleware(lambda _request: None)
                response = middleware(RequestFactory().get("/static/styles.css"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/css"))

    def test_admin_page_renders_full_page_admin_view(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<body class="admin-page" data-admin-page="true">')
        self.assertContains(response, 'class="admin-back-link" href="/">Back to website</a>')

    def test_admin_login_protects_destination_crud_and_logout_revokes_session(self):
        payload = {
            "name": "Test destination",
            "description": "A sufficiently long description for this test destination.",
            "region": "Gaya",
            "category": "Heritage",
        }
        denied = self.client.post("/api/places", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(denied.status_code, 401)

        login = self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "ADMIN", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.cookies["beyond_admin_session"]["httponly"])
        self.assertEqual(self.client.get("/api/admin/session").status_code, 200)

        with patch("tourism.views.upload_place_image") as upload, patch("tourism.views.delete_place_image"):
            created = self.client.post(
                "/api/places",
                data={**payload, "image": self.valid_place_image()},
            )
        self.assertEqual(created.status_code, 201)
        place_id = created.json()["id"]
        upload.assert_called_once()
        self.assertNotIn("image", {field.name for field in Place._meta.fields})
        updated = self.client.patch(
            f"/api/places/{place_id}",
            data=json.dumps({"description": "An updated description with enough characters."}),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["description"], "An updated description with enough characters.")
        with patch("tourism.views.delete_place_image") as delete_image:
            self.assertEqual(self.client.delete(f"/api/places/{place_id}").status_code, 204)
        delete_image.assert_called_once_with(place_id)

        self.assertEqual(self.client.post("/api/admin/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/admin/session").status_code, 401)
        self.assertEqual(self.client.post("/api/places", data=json.dumps(payload), content_type="application/json").status_code, 401)

    def test_place_fields_are_required_and_whitespace_is_rejected(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        valid_payload = {
            "name": "Valid place",
            "description": "A valid destination description.",
            "region": "Gaya",
            "category": "Heritage",
        }
        for field in valid_payload:
            with self.subTest(field=field):
                payload = {**valid_payload, field: "   "}
                response = self.client.post(
                    "/api/places",
                    data={**payload, "image": self.valid_place_image()},
                )
                self.assertEqual(response.status_code, 422)
        missing_image = self.client.post("/api/places", data=valid_payload)
        self.assertEqual(missing_image.status_code, 422)
        self.assertFalse(Place.objects.exists())

    def test_place_image_upload_replacement_and_public_s3_redirect(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        with patch("tourism.views.upload_place_image") as upload:
            response = self.client.post(
                "/api/places",
                data={
                    "name": "Image place",
                    "description": "A destination with a directly uploaded image.",
                    "region": "Gaya",
                    "category": "Heritage",
                    "image": self.valid_place_image(),
                },
            )
            self.assertEqual(response.status_code, 201)
            place_id = response.json()["id"]
            self.assertEqual(response.json()["image"], f"/api/places/{place_id}/image")
            self.assertEqual(upload.call_args.args[0], place_id)
            self.assertEqual(upload.call_args.args[2], "image/png")

            replacement = self.client.generic(
                "PATCH",
                f"/api/places/{place_id}",
                encode_multipart(BOUNDARY, {"image": self.valid_place_image()}),
                content_type=MULTIPART_CONTENT,
            )
            self.assertEqual(replacement.status_code, 200)
            self.assertEqual(upload.call_count, 2)

        with patch("tourism.views.get_place_image_url", return_value="https://s3.example/signed-image"):
            image_response = self.client.get(f"/api/places/{place_id}/image")
        self.assertEqual(image_response.status_code, 302)
        self.assertEqual(image_response["Location"], "https://s3.example/signed-image")

    def test_invalid_place_image_is_rejected(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        response = self.client.post(
            "/api/places",
            data={
                "name": "Image place",
                "description": "A destination with an invalid image file.",
                "region": "Gaya",
                "category": "Heritage",
                "image": SimpleUploadedFile("not-an-image.txt", b"not an image", content_type="text/plain"),
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Place.objects.exists())

    def test_s3_client_uses_regional_virtual_host_addressing_for_signed_links(self):
        credentials = {
            "Access_key": "test-access-key",
            "Secret_access_key": "test-secret-key",
            "Region": "ap-south-1",
            "S3bucket": "test-bucket",
        }
        for name, value in credentials.items():
            StoredCredential.objects.create(
                service="AWS",
                name=name,
                encrypted_secret=encrypt_credential(value),
            )

        with patch("tourism.s3_storage.boto3.client") as client_factory:
            from tourism.s3_storage import get_s3_client

            get_s3_client()

        config = client_factory.call_args.kwargs["config"]
        self.assertEqual(config.s3, {"addressing_style": "virtual"})

    @staticmethod
    def valid_place_image():
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="red").save(image_buffer, format="PNG")
        return SimpleUploadedFile("place.png", image_buffer.getvalue(), content_type="image/png")

    def test_invalid_admin_password_is_rejected(self):
        response = self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "incorrect"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_credentials_require_admin_and_are_encrypted_and_never_returned(self):
        secret = "sample-secret-value"
        payload = {"service": "AWS", "name": "Secret access key", "secret": secret}
        self.assertEqual(self.client.get("/api/admin/credentials").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/admin/credentials",
                data=json.dumps(payload),
                content_type="application/json",
            ).status_code,
            401,
        )
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        with self.settings(SECRET_KEY="test-django-secret-key"):
            response = self.client.post(
                "/api/admin/credentials",
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)
            self.assertNotIn("secret", response.json())
            stored = StoredCredential.objects.get(service="AWS", name="Secret access key")
            self.assertNotEqual(stored.encrypted_secret, secret)
            self.assertEqual(decrypt_credential(stored.encrypted_secret), secret)

            listing = self.client.get("/api/admin/credentials")
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(len(listing.json()), 1)
            self.assertNotIn("secret", listing.json()[0])
            self.assertNotIn("encrypted_secret", listing.json()[0])

            updated = self.client.post(
                "/api/admin/credentials",
                data=json.dumps({**payload, "secret": "rotated-secret"}),
                content_type="application/json",
            )
            self.assertEqual(updated.status_code, 201)
            self.assertEqual(StoredCredential.objects.count(), 1)
            self.assertEqual(
                decrypt_credential(StoredCredential.objects.get().encrypted_secret),
                "rotated-secret",
            )
            self.assertEqual(self.client.delete(f"/api/admin/credentials/{stored.id}").status_code, 204)
            self.assertFalse(StoredCredential.objects.exists())

    def test_credentials_use_django_secret_key_without_extra_encryption_setting(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        response = self.client.post(
            "/api/admin/credentials",
            data=json.dumps({"service": "AWS", "name": "Access key ID", "secret": "value"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        stored = StoredCredential.objects.get()
        self.assertNotEqual(stored.encrypted_secret, "value")
        self.assertEqual(decrypt_credential(stored.encrypted_secret), "value")

    def test_stored_credentials_api_authenticates_and_decrypts_on_read(self):
        api_username = "credentials-client"
        api_password = "client-password"
        StoredCredentialApiUser.objects.create(
            username=api_username,
            password_hash=make_password(api_password),
        )
        basic_token = base64.b64encode(f"{api_username}:{api_password}".encode()).decode("ascii")
        headers = {"HTTP_AUTHORIZATION": f"Basic {basic_token}"}
        payload = {"service": "AWS", "name": "Access key", "value": "plain-input-secret"}

        self.assertEqual(self.client.get("/api/stored-credentials").status_code, 401)
        with self.settings(SECRET_KEY="test-django-secret-key"):
            encrypted_field_payload = {
                "service": "AWS",
                "name": "Access key",
                "secret": "this API field is not accepted",
            }
            rejected = self.client.post(
                "/api/stored-credentials",
                data=json.dumps(encrypted_field_payload),
                content_type="application/json",
                **headers,
            )
            self.assertEqual(rejected.status_code, 422)

            created = self.client.post(
                "/api/stored-credentials",
                data=json.dumps(payload),
                content_type="application/json",
                **headers,
            )
            self.assertEqual(created.status_code, 201)
            self.assertRegex(
                created.json()["updated_at"],
                r"T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?$",
            )
            stored = StoredCredential.objects.get(service="AWS", name="Access key")
            self.assertEqual(stored.service, "AWS")
            self.assertEqual(stored.name, "Access key")
            self.assertNotEqual(stored.encrypted_secret, payload["value"])

            retrieved = self.client.get("/api/stored-credentials?service=aws", **headers)
            self.assertEqual(retrieved.status_code, 200)
            self.assertEqual(retrieved.json()[0]["value"], payload["value"])
            self.assertRegex(
                retrieved.json()[0]["updated_at"],
                r"T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?$",
            )

            updated = self.client.post(
                "/api/stored-credentials",
                data=json.dumps({**payload, "value": "rotated-secret"}),
                content_type="application/json",
                **headers,
            )
            self.assertEqual(updated.status_code, 201)
            self.assertEqual(StoredCredential.objects.count(), 1)
            retrieved = self.client.get("/api/stored-credentials", **headers)
            self.assertEqual(retrieved.json()[0]["value"], "rotated-secret")
            self.assertEqual(
                self.client.delete(
                    f"/api/stored-credentials/{stored.id}",
                    **headers,
                ).status_code,
                204,
            )
            self.assertFalse(StoredCredential.objects.exists())

    def test_stored_credentials_api_rejects_bad_basic_auth(self):
        response = self.client.get(
            "/api/stored-credentials",
            HTTP_AUTHORIZATION="Basic invalid-token",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], 'Basic realm="Stored credentials API"')

    @patch("tourism.views.fetch_location_pincodes", return_value=["823001", "800001"])
    def test_admin_can_create_list_and_remove_hotels_restaurants_vans_and_guides(self, _mock_pincodes):
        examples = (
            (
                "hotels",
                Hotel,
                {
                    "name": "Bodh Gaya Inn",
                    "air_conditioning": "AC",
                    "price_range": "₹2,000–₹4,000 per night",
                    "star_rating": 4,
                    "locations": [
                        {
                            "state": "Bihar",
                            "city": "Gaya",
                            "postal_code": "823001",
                            "contact_info": "+91 9876543210",
                            "address": "Temple Road, Bodh Gaya",
                        },
                        {
                            "state": "Bihar",
                            "city": "Patna",
                            "postal_code": "800001",
                            "contact_info": "+91 9876543211",
                            "address": "Fraser Road, Patna",
                        },
                    ],
                },
            ),
            (
                "restaurants",
                Restaurant,
                {
                    "name": "Lotus Kitchen",
                    "state": "Bihar",
                    "city": "Gaya",
                    "postal_code": "823001",
                    "contact_info": "lotus@example.com",
                    "address": "Main Road, Bodh Gaya",
                    "food_type": "Veg",
                    "price_range": "Medium",
                },
            ),
            (
                "guides",
                Guide,
                {
                    "name": "A local guide",
                    "contact_info": "+91 9876543210",
                    "state": "Bihar",
                    "city": "Gaya",
                    "postal_code": "823001",
                    "languages": "Hindi, English, Pali, Tibetan, Korean",
                    "price": "1500.00",
                },
            ),
            (
                "vans",
                Van,
                {
                    "name": "Bodh Gaya Van Service",
                    "state": "Bihar",
                    "city": "Gaya",
                    "postal_code": "823001",
                    "contact_info": "+91 9876543210",
                    "address": "Temple Road, Bodh Gaya",
                    "vehicle_type": "AC Van",
                    "seat_capacity": 12,
                    "booking_charge_per_day": "3000.00",
                    "per_km_charge": "15.00",
                },
            ),
        )
        for listing_type, model, payload in examples:
            with self.subTest(listing_type=listing_type):
                endpoint = f"/api/admin/listings/{listing_type}"
                self.assertEqual(self.client.get(endpoint).status_code, 401)
                response = self.client.post(
                    "/api/admin/login",
                    data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)

                created = self.client.post(endpoint, data=json.dumps(payload), content_type="application/json")
                self.assertEqual(created.status_code, 201)
                self.assertEqual(created.json()["name"], payload["name"])
                if listing_type == "guides":
                    self.assertEqual(created.json()["languages"], payload["languages"])
                    self.assertEqual(GuideLanguage.objects.filter(name__iexact="Korean").count(), 1)
                self.assertEqual(model.objects.count(), 1)
                if listing_type == "hotels":
                    self.assertEqual(len(created.json()["locations"]), 2)
                    self.assertEqual(HotelLocation.objects.filter(hotel_id=created.json()["id"]).count(), 2)

                listed = self.client.get(endpoint)
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()[0]["name"], payload["name"])
                if listing_type == "vans":
                    self.assertEqual(listed.json()[0]["booking_charge_per_day"], "3000.00")
                    self.assertEqual(listed.json()[0]["per_km_charge"], "15.00")
                    self.assertNotIn("price_range", listed.json()[0])
                if listing_type == "hotels":
                    self.assertEqual(len(listed.json()[0]["locations"]), 2)
                    self.assertEqual(
                        {location["city"] for location in listed.json()[0]["locations"]},
                        {"Gaya", "Patna"},
                    )
                deleted = self.client.delete(f"{endpoint}/{created.json()['id']}")
                self.assertEqual(deleted.status_code, 204)
                self.assertFalse(model.objects.exists())
                self.client.post("/api/admin/logout")

    def test_van_api_rejects_tempo_traveller_and_missing_charge(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        van = {
            "name": "Van Service",
            "state": "Bihar",
            "city": "Gaya",
            "postal_code": "823001",
            "contact_info": "+91 9876543210",
            "address": "Temple Road",
            "vehicle_type": "AC Van",
            "seat_capacity": 8,
            "booking_charge_per_day": "3000",
            "per_km_charge": "15",
        }
        invalid_type = self.client.post(
            "/api/admin/listings/vans",
            data=json.dumps({**van, "vehicle_type": "Tempo Traveller"}),
            content_type="application/json",
        )
        self.assertEqual(invalid_type.status_code, 422)

        missing_charge = self.client.post(
            "/api/admin/listings/vans",
            data=json.dumps({key: value for key, value in van.items() if key != "per_km_charge"}),
            content_type="application/json",
        )
        self.assertEqual(missing_charge.status_code, 422)
        self.assertFalse(Van.objects.exists())

    @patch("tourism.views.fetch_location_pincodes", return_value=["823001"])
    def test_hotel_website_is_optional_and_returned_by_api(self, _mock_pincodes):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        payload = {
            "name": "Website Hotel",
            "air_conditioning": "AC",
            "price_range": "Medium",
            "star_rating": 3,
            "website": "https://example.com/hotel",
            "locations": [
                {
                    "state": "Bihar",
                    "city": "Gaya",
                    "postal_code": "823001",
                    "contact_info": "1234567890",
                    "address": "Temple Road",
                }
            ],
        }
        created = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["website"], payload["website"])
        listed = self.client.get("/api/admin/listings/hotels")
        self.assertEqual(listed.json()[0]["website"], payload["website"])

        payload.pop("website")
        created_without_website = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(created_without_website.status_code, 201)
        self.assertEqual(created_without_website.json()["website"], "")

    def test_admin_listing_validation_rejects_invalid_categories_and_missing_fields(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        invalid_restaurant = {
            "name": "Test Place",
            "state": "Bihar",
            "city": "Gaya",
            "postal_code": "823001",
            "contact_info": "1234567890",
            "address": "Test address",
            "food_type": "Both",
            "price_range": "Medium",
        }
        response = self.client.post(
            "/api/admin/listings/restaurants",
            data=json.dumps(invalid_restaurant),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Restaurant.objects.exists())

        response = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps({"name": "Incomplete"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Hotel.objects.exists())

        invalid_hotel = {
            "name": "Test Hotel",
            "air_conditioning": "AC",
            "price_range": "Medium",
            "star_rating": 3,
            "locations": [
                {
                    "state": "Bihar",
                    "city": "Gaya",
                    "postal_code": "823001",
                    "contact_info": "1234567890",
                    "address": "Test address",
                }
            ],
        }
        invalid_hotel["star_rating"] = 0
        response = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps(invalid_hotel),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Hotel.objects.exists())

        invalid_hotel["star_rating"] = 8
        response = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps(invalid_hotel),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Hotel.objects.exists())

    def test_listing_locations_are_selected_from_state_city_reference_data(self):
        response = self.client.get("/")
        self.assertContains(response, 'data-location-state')
        self.assertContains(response, 'data-location-city')
        self.assertContains(response, 'data-location-pincode')
        self.assertContains(response, "Andaman and Nicobar Islands")

    @patch("tourism.views.urlopen")
    def test_pincode_lookup_returns_codes_for_the_selected_state_and_city(self, mocked_urlopen):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        response_body = json.dumps(
            [
                {
                    "Status": "Success",
                    "PostOffice": [
                        {"State": "Bihar", "District": "Gaya", "Name": "Gaya H.O.", "Pincode": "823001"},
                        {"State": "Bihar", "District": "Patna", "Name": "Gaya Road", "Pincode": "800001"},
                        {"State": "Tamil Nadu", "District": "Gaya", "Name": "Gaya", "Pincode": "600001"},
                    ],
                }
            ]
        ).encode()
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = response_body

        response = self.client.get("/api/location-pincodes", {"state": "Bihar", "city": "Gaya"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["823001"])
        self.assertIn("Gaya", mocked_urlopen.call_args.args[0])

    def test_pincode_lookup_rejects_city_outside_selected_state(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        response = self.client.get("/api/location-pincodes", {"state": "Bihar", "city": "Mumbai"})
        self.assertEqual(response.status_code, 422)

    def test_listing_accepts_other_city_and_six_digit_pincode(self):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        hotel = {
            "name": "Custom City Hotel",
            "air_conditioning": "AC",
            "price_range": "Medium",
            "star_rating": 3,
            "locations": [
                {
                    "state": "Bihar",
                    "city": "A village not in the city list",
                    "postal_code": "823099",
                    "contact_info": "1234567890",
                    "address": "Test address",
                    "city_is_other": True,
                    "postal_code_is_other": True,
                }
            ],
        }
        with patch("tourism.views.fetch_location_pincodes") as lookup:
            response = self.client.post(
                "/api/admin/listings/hotels",
                data=json.dumps(hotel),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["locations"][0]["city"], hotel["locations"][0]["city"])
        self.assertEqual(response.json()["locations"][0]["postal_code"], hotel["locations"][0]["postal_code"])
        lookup.assert_not_called()
        self.assertTrue(
            CityPincode.objects.filter(
                state="Bihar",
                city=hotel["locations"][0]["city"],
                postal_code=hotel["locations"][0]["postal_code"],
            ).exists()
        )
        self.assertEqual(
            CityPincode.objects.filter(
                state="Bihar",
                city=hotel["locations"][0]["city"],
                postal_code=hotel["locations"][0]["postal_code"],
            ).count(),
            1,
        )
        repeated_pincode = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps(hotel),
            content_type="application/json",
        )
        self.assertEqual(repeated_pincode.status_code, 201)
        self.assertEqual(
            CityPincode.objects.filter(
                state="Bihar",
                city=hotel["locations"][0]["city"],
                postal_code=hotel["locations"][0]["postal_code"],
            ).count(),
            1,
        )

        response = self.client.get(
            "/api/location-pincodes",
            {"state": "Bihar", "city": hotel["locations"][0]["city"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["823099"])
        self.assertContains(self.client.get("/"), hotel["locations"][0]["city"])
        self.assertIn(hotel["locations"][0]["city"], self.client.get("/").context["state_cities"]["Bihar"])

        hotel["locations"][0].update(
            city="Gaya",
            postal_code="823001",
            city_is_other=False,
            postal_code_is_other=True,
        )
        with patch("tourism.views.fetch_location_pincodes", return_value=["823001"]):
            response = self.client.post(
                "/api/admin/listings/hotels",
                data=json.dumps(hotel),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 201)
        self.client.delete(f"/api/admin/listings/hotels/{response.json()['id']}")

        hotel["locations"][0]["postal_code"] = "1234"
        response = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps({**hotel, "postal_code_is_other": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    @patch("tourism.views.fetch_location_pincodes", return_value=["823001", "800001"])
    def test_listing_rejects_a_pincode_not_mapped_to_its_city(self, _mock_pincodes):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        hotel = {
            "name": "Test Hotel",
            "state": "Bihar",
            "city": "Gaya",
            "postal_code": "800001",
            "contact_info": "1234567890",
            "address": "Test address",
            "air_conditioning": "AC",
            "price_range": "Medium",
            "star_rating": 3,
        }
        response = self.client.post(
            "/api/admin/listings/hotels",
            data=json.dumps(hotel),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Hotel.objects.exists())

    @patch("tourism.views.fetch_location_pincodes", return_value=["823001"])
    def test_custom_guide_languages_are_reused_without_case_duplicates(self, _mock_pincodes):
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )
        guide = {
            "name": "First Guide",
            "contact_info": "1234567890",
            "state": "Bihar",
            "city": "Gaya",
            "postal_code": "823001",
            "languages": "Hindi, Spanish, spanish",
            "price": "1200.00",
        }
        first = self.client.post(
            "/api/admin/listings/guides",
            data=json.dumps(guide),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["languages"], "Hindi, Spanish")
        self.assertEqual(GuideLanguage.objects.filter(name__iexact="Spanish").count(), 1)

        guide["name"] = "Second Guide"
        guide["languages"] = "SPANISH, English"
        second = self.client.post(
            "/api/admin/listings/guides",
            data=json.dumps(guide),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["languages"], "SPANISH, English")
        self.assertEqual(GuideLanguage.objects.filter(name__iexact="Spanish").count(), 1)

        homepage = self.client.get("/")
        self.assertContains(homepage, 'value="Spanish" data-guide-language')
        self.assertEqual(homepage.content.count(b'value="Spanish" data-guide-language'), 1)

    def test_public_place_filter_and_booking_creation(self):
        Place.objects.create(
            name="Nalanda test",
            description="An ancient destination description for API tests.",
            region="Nalanda",
            category="Heritage",
        )
        places = self.client.get("/api/places?region=nalanda")
        self.assertEqual(places.status_code, 200)
        self.assertEqual([place["name"] for place in places.json()], ["Nalanda test"])

        booking = {
            "booking_type": ["complete-trip", "cab", "guided"],
            "name": "Traveler",
            "email": "traveler@example.com",
            "phone": "+911234567890",
            "destination": "Rajgir",
            "travel_date": "2026-11-20",
            "guests": 2,
        }
        booking["destination"] = ["Gaya", "Rajgir"]
        with patch("tourism.views.queue_notification_email") as queue_notification:
            response = self.client.post("/api/bookings", data=json.dumps(booking), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["booking_type"], "complete-trip, cab, guided")
        self.assertEqual(response.json()["destination"], "Gaya, Rajgir")
        self.assertEqual(Booking.objects.get().destination, "Gaya, Rajgir")
        queue_notification.assert_called_once()
        self.assertIn("Destination: Gaya, Rajgir", queue_notification.call_args.args[1])
        self.assertIn("Plan my complete trip, Cab / private van, Guided visit", queue_notification.call_args.args[1])
        self.assertEqual(Booking.objects.count(), 1)
        planned = PlanningRequest.objects.get()
        self.assertEqual(planned.request_type, "trip")
        self.assertEqual(planned.services, "Plan my complete trip, Cab / private van, Guided visit")
        self.assertEqual(planned.destinations, "Gaya, Rajgir")
        self.assertEqual(planned.guests, 2)

    def test_booking_with_all_services_fits_database_field(self):
        booking = {
            "booking_type": ["complete-trip", "hotel", "cab", "guided"],
            "name": "Traveler",
            "email": "traveler@example.com",
            "phone": "+911234567890",
            "destination": ["Bodh Gaya", "Gaya", "Nalanda", "Rajgir"],
            "travel_date": "2026-10-29",
            "guests": 2,
            "notes": "this is test",
        }
        with patch("tourism.views.queue_notification_email") as queue_notification:
            response = self.client.post(
                "/api/bookings",
                data=json.dumps(booking),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Booking.objects.get().booking_type,
            "complete-trip, hotel, cab, guided",
        )
        self.assertIn("Bodh Gaya, Gaya, Nalanda, Rajgir", queue_notification.call_args.args[1])

    def test_booking_is_not_saved_when_notification_cannot_be_queued(self):
        booking = {
            "booking_type": "cab",
            "name": "Traveler",
            "email": "traveler@example.com",
            "phone": "+911234567890",
            "destination": ["Gaya"],
            "travel_date": "2026-11-20",
            "guests": 2,
        }
        with patch(
            "tourism.views.queue_notification_email",
            side_effect=CommandError("Email queue is unavailable."),
        ):
            response = self.client.post("/api/bookings", data=json.dumps(booking), content_type="application/json")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(PlanningRequest.objects.count(), 0)

    def test_invalid_email_and_booking_type_are_rejected(self):
        inquiry = {"name": "Traveler", "email": "not-an-email", "message": "A sufficiently long inquiry message."}
        inquiry["arrangements"] = ["complete-trip"]
        response = self.client.post("/api/inquiries", data=json.dumps(inquiry), content_type="application/json")
        self.assertEqual(response.status_code, 422)

        inquiry["email"] = "traveler@example.com"
        response = self.client.post("/api/inquiries", data=json.dumps(inquiry), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["email_queued"])

        booking = {
            "booking_type": "plane",
            "name": "Traveler",
            "email": "traveler@example.com",
            "phone": "+911234567890",
            "destination": "Rajgir",
            "travel_date": "2026-11-20",
        }
        response = self.client.post("/api/bookings", data=json.dumps(booking), content_type="application/json")
        self.assertEqual(response.status_code, 422)

    def test_contact_inquiry_emails_arrangements_using_shared_smtp(self):
        inquiry = {
            "name": "Traveler",
            "email": "traveler@example.com",
            "arrangements": ["accommodation", "guided-visits"],
            "message": "Please help plan my visit.",
        }
        with patch("tourism.views.queue_notification_email") as queue_notification:
            response = self.client.post(
                "/api/inquiries",
                data=json.dumps(inquiry),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["email_queued"])
        queue_notification.assert_called_once()
        subject, body = queue_notification.call_args.args
        self.assertIn("Traveler", subject)
        self.assertIn("Accommodation / stay", body)
        self.assertIn("Guided visits and tours", body)
        self.assertIn("Please help plan my visit.", body)
        self.assertIn("Guided visits and tours", Inquiry.objects.get().message)
        planned = PlanningRequest.objects.get()
        self.assertEqual(planned.request_type, "inquiry")
        self.assertEqual(planned.arrangements, "Accommodation / stay, Guided visits and tours")
        self.assertEqual(planned.message, inquiry["message"])

    def test_contact_inquiry_reports_smtp_failure_without_false_success(self):
        inquiry = {
            "name": "Traveler",
            "email": "traveler@example.com",
            "arrangements": ["complete-trip"],
            "message": "Please help plan my visit.",
        }
        with patch(
            "tourism.views.queue_notification_email",
            side_effect=CommandError("Email queue is unavailable."),
        ):
            response = self.client.post(
                "/api/inquiries",
                data=json.dumps(inquiry),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(Inquiry.objects.count(), 0)
        self.assertEqual(PlanningRequest.objects.count(), 0)

    def test_notification_delivery_runs_in_background_and_updates_outbox(self):
        with (
            patch("tourism.email_utils.send_notification_email") as send_email,
            patch("tourism.email_utils.threading.Thread") as thread,
        ):
            from tourism.email_utils import _deliver_notification, queue_notification_email

            thread.return_value.start.side_effect = lambda: _deliver_notification(
                thread.call_args.kwargs["args"][0]
            )
            with self.captureOnCommitCallbacks(execute=True):
                queued = queue_notification_email("Queued notification", "Queued body.")
            self.assertEqual(queued.status, NotificationOutbox.Status.QUEUED)
            thread.return_value.start.assert_called_once()
            send_email.assert_called_once_with("Queued notification", "Queued body.")
        queued.refresh_from_db()
        self.assertEqual(queued.status, NotificationOutbox.Status.SENT)
        self.assertIsNotNone(queued.sent_at)

    def test_notification_delivery_records_smtp_failure_without_blocking_request(self):
        notification = NotificationOutbox.objects.create(
            subject="Failed notification",
            body="A test message.",
        )
        from tourism.email_utils import _deliver_notification

        with patch(
            "tourism.email_utils.send_notification_email",
            side_effect=CommandError("SMTP is unavailable."),
        ):
            _deliver_notification(notification.id)

        notification.refresh_from_db()
        self.assertEqual(notification.status, NotificationOutbox.Status.FAILED)
        self.assertEqual(notification.error, "SMTP is unavailable.")

    def test_planning_requests_admin_api_lists_updates_and_deletes_records(self):
        planning_request = PlanningRequest.objects.create(
            request_type="trip",
            name="Traveler",
            email="traveler@example.com",
            phone="+911234567890",
            services="Cab / private van",
            destinations="Gaya",
            travel_date="2026-11-20",
            guests=2,
            message="Morning visit",
        )
        self.assertEqual(self.client.get("/api/admin/planning-requests").status_code, 401)
        self.assertEqual(
            self.client.patch(
                f"/api/admin/planning-requests/{planning_request.id}",
                data=json.dumps({"name": "Updated traveler"}),
                content_type="application/json",
            ).status_code,
            401,
        )
        self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "test-password-long-enough"}),
            content_type="application/json",
        )

        listing = self.client.get("/api/admin/planning-requests")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["id"], planning_request.id)
        self.assertEqual(listing.json()[0]["services"], "Cab / private van")

        updated = self.client.patch(
            f"/api/admin/planning-requests/{planning_request.id}",
            data=json.dumps({"name": "Updated traveler", "guests": 3}),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Updated traveler")
        self.assertEqual(updated.json()["guests"], 3)

        invalid = self.client.patch(
            f"/api/admin/planning-requests/{planning_request.id}",
            data=json.dumps({"email": "not-an-email"}),
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(
            self.client.delete(f"/api/admin/planning-requests/{planning_request.id}").status_code,
            204,
        )
        self.assertFalse(PlanningRequest.objects.exists())
