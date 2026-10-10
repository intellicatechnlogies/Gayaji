from django.db import models


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
