from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower


class Place(models.Model):
    name = models.CharField(max_length=160, db_index=True)
    description = models.TextField()
    image = models.CharField(max_length=1000)
    region = models.CharField(max_length=100, default="Bodh Gaya")
    category = models.CharField(max_length=100, default="Heritage")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "places"
        ordering = ("region", "name")


class Inquiry(models.Model):
    name = models.CharField(max_length=160)
    email = models.CharField(max_length=254)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inquiries"
        ordering = ("-created_at",)


class Booking(models.Model):
    booking_type = models.CharField(max_length=30)
    name = models.CharField(max_length=160)
    email = models.CharField(max_length=254)
    phone = models.CharField(max_length=40)
    destination = models.CharField(max_length=160)
    travel_date = models.CharField(max_length=30)
    guests = models.IntegerField(default=1)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bookings"
        ordering = ("-created_at",)


class AdminAccount(models.Model):
    username = models.CharField(max_length=80, unique=True)
    password_hash = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_accounts"


class AdminSession(models.Model):
    token_hash = models.CharField(max_length=64, primary_key=True)
    admin = models.ForeignKey(AdminAccount, on_delete=models.CASCADE, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_sessions"


class CityPincode(models.Model):
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=6, validators=(RegexValidator(r"^\d{6}$"),))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "city_pincodes"
        ordering = ("state", "city", "postal_code")
        constraints = [
            models.UniqueConstraint(fields=("state", "city", "postal_code"), name="unique_city_pincode")
        ]


class GuideLanguage(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "guide_languages"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="unique_guide_language_ci")
        ]


class StoredCredential(models.Model):
    service = models.CharField(max_length=100)
    name = models.CharField(max_length=120)
    encrypted_secret = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stored_credentials"
        ordering = ("service", "name")
        constraints = [
            models.UniqueConstraint(fields=("service", "name"), name="unique_stored_credential_name")
        ]


class StoredCredentialApiUser(models.Model):
    username = models.CharField(max_length=80, unique=True)
    password_hash = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stored_credential_api_users"


class Hotel(models.Model):
    name = models.CharField(max_length=160)
    website = models.URLField(max_length=500, blank=True)
    air_conditioning = models.CharField(max_length=10, choices=(("AC", "AC"), ("Non-AC", "Non-AC")))
    price_range = models.CharField(max_length=100)
    star_rating = models.PositiveSmallIntegerField(
        choices=tuple((rating, str(rating)) for rating in range(1, 8)),
        validators=(MinValueValidator(1),),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hotels"
        ordering = ("name",)


class HotelLocation(models.Model):
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name="locations")
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=6, blank=True, validators=(RegexValidator(r"^\d{6}$"),))
    contact_info = models.CharField(max_length=160)
    address = models.TextField()

    class Meta:
        db_table = "hotel_locations"
        ordering = ("state", "city", "address")


class Restaurant(models.Model):
    name = models.CharField(max_length=160)
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=6, blank=True, validators=(RegexValidator(r"^\d{6}$"),))
    contact_info = models.CharField(max_length=160)
    address = models.TextField()
    food_type = models.CharField(max_length=10, choices=(("Veg", "Veg"), ("Non-veg", "Non-veg")))
    price_range = models.CharField(
        max_length=20,
        choices=(("Non-premium", "Non-premium"), ("Medium", "Medium"), ("Premium", "Premium")),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "restaurants"
        ordering = ("name",)


class Guide(models.Model):
    name = models.CharField(max_length=160)
    contact_info = models.CharField(max_length=160)
    state = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=6, blank=True, validators=(RegexValidator(r"^\d{6}$"),))
    languages = models.CharField(max_length=300)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=(MinValueValidator(0),))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "guides"
        ordering = ("name",)
