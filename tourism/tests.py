import json

from django.test import TestCase

from .models import AdminAccount, Booking, Place
from .views import hash_password


class TourismApiTests(TestCase):
    def setUp(self):
        self.admin = AdminAccount.objects.create(
            username="admin",
            password_hash=hash_password("test-password-long-enough"),
        )

    def test_homepage_uses_django_template_and_renders_database_destinations(self):
        Place.objects.create(
            name="Template destination",
            description="A sufficiently detailed place description for the rendered page.",
            image="https://example.com/destination.jpg",
            region="Nalanda",
            category="Heritage",
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tourism/home.html")
        self.assertContains(response, "Template destination")
        self.assertContains(response, 'id="admin-panel"')
        self.assertContains(response, 'id="booking-backdrop"')

    def test_admin_login_protects_destination_crud_and_logout_revokes_session(self):
        payload = {
            "name": "Test destination",
            "description": "A sufficiently long description for this test destination.",
            "image": "https://example.com/place.jpg",
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

        created = self.client.post("/api/places", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(created.status_code, 201)
        place_id = created.json()["id"]
        updated = self.client.patch(
            f"/api/places/{place_id}",
            data=json.dumps({"description": "An updated description with enough characters."}),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["description"], "An updated description with enough characters.")
        self.assertEqual(self.client.delete(f"/api/places/{place_id}").status_code, 204)

        self.assertEqual(self.client.post("/api/admin/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/admin/session").status_code, 401)
        self.assertEqual(self.client.post("/api/places", data=json.dumps(payload), content_type="application/json").status_code, 401)

    def test_invalid_admin_password_is_rejected(self):
        response = self.client.post(
            "/api/admin/login",
            data=json.dumps({"username": "admin", "password": "incorrect"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_public_place_filter_and_booking_creation(self):
        Place.objects.create(
            name="Nalanda test",
            description="An ancient destination description for API tests.",
            image="https://example.com/nalanda.jpg",
            region="Nalanda",
            category="Heritage",
        )
        places = self.client.get("/api/places?region=nalanda")
        self.assertEqual(places.status_code, 200)
        self.assertEqual([place["name"] for place in places.json()], ["Nalanda test"])

        booking = {
            "booking_type": "cab",
            "name": "Traveler",
            "email": "traveler@example.com",
            "phone": "+911234567890",
            "destination": "Rajgir",
            "travel_date": "2026-11-20",
            "guests": 2,
        }
        response = self.client.post("/api/bookings", data=json.dumps(booking), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["booking_type"], "cab")
        self.assertEqual(Booking.objects.count(), 1)

    def test_invalid_email_and_booking_type_are_rejected(self):
        inquiry = {"name": "Traveler", "email": "not-an-email", "message": "A sufficiently long inquiry message."}
        response = self.client.post("/api/inquiries", data=json.dumps(inquiry), content_type="application/json")
        self.assertEqual(response.status_code, 422)

        inquiry["email"] = "traveler@example.com"
        response = self.client.post("/api/inquiries", data=json.dumps(inquiry), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["email_sent"])

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
