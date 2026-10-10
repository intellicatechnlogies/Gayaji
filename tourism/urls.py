from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("admin/login", views.admin_login, name="admin-login"),
    path("admin/session", views.admin_session_status, name="admin-session"),
    path("admin/logout", views.admin_logout, name="admin-logout"),
    path("places", views.places, name="places"),
    path("places/<int:place_id>", views.place_detail, name="place-detail"),
    path("inquiries", views.create_inquiry, name="inquiries"),
    path("bookings", views.create_booking, name="bookings"),
    path("bookings/<str:booking_type>", views.create_typed_booking, name="typed-bookings"),
    path("admin/inquiries", views.admin_inquiries, name="admin-inquiries"),
    path("admin/bookings", views.admin_bookings, name="admin-bookings"),
]
