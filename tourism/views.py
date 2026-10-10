import hashlib
import json
import secrets
import smtplib
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import AdminAccount, AdminSession, Booking, Inquiry, Place

ADMIN_SESSION_COOKIE = "beyond_admin_session"
ADMIN_SESSION_DURATION = timedelta(hours=12)
PLACE_FIELDS = {
    "name": (2, 160),
    "description": (10, None),
    "image": (5, 1000),
    "region": (2, 100),
    "category": (2, 100),
}


def json_body(request: HttpRequest) -> tuple[dict | None, JsonResponse | None]:
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Request body must be valid JSON"}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"detail": "Request body must be a JSON object"}, status=400)
    return data, None


def validate_fields(data: dict, rules: dict, *, partial: bool = False) -> dict:
    errors = {}
    for field, (minimum, maximum) in rules.items():
        if partial and field not in data:
            continue
        value = data.get(field)
        if not isinstance(value, str):
            errors[field] = "This field is required and must be text."
            continue
        if len(value) < minimum or (maximum is not None and len(value) > maximum):
            errors[field] = f"Must be between {minimum} and {maximum or 'unlimited'} characters."
    return errors


def validate_contact(data: dict, *, booking: bool = False) -> dict:
    rules = {"name": (2, 160), "email": (1, 254)}
    if booking:
        rules.update(
            phone=(7, 40),
            destination=(2, 160),
            travel_date=(8, 30),
        )
    else:
        rules["message"] = (10, 5000)
    errors = validate_fields(data, rules)
    if "email" not in errors:
        try:
            validate_email(data["email"])
        except ValidationError:
            errors["email"] = "Enter a valid email address."
    if booking:
        booking_type = data.get("booking_type")
        if booking_type not in {"hotel", "cab", "guided"}:
            errors["booking_type"] = "Must be hotel, cab or guided."
        guests = data.get("guests", 1)
        if isinstance(guests, bool) or not isinstance(guests, int) or not 1 <= guests <= 30:
            errors["guests"] = "Must be a whole number between 1 and 30."
        notes = data.get("notes")
        if notes is not None and (not isinstance(notes, str) or len(notes) > 2000):
            errors["notes"] = "Must be text of no more than 2000 characters."
    return errors


def place_data(place: Place) -> dict:
    return {
        "id": place.id,
        "name": place.name,
        "description": place.description,
        "image": place.image,
        "region": place.region,
        "category": place.category,
    }


def booking_data(booking: Booking) -> dict:
    return {
        "id": booking.id,
        "booking_type": booking.booking_type,
        "name": booking.name,
        "destination": booking.destination,
        "travel_date": booking.travel_date,
    }


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
        maxmem=128 * 1024 * 1024,
    )
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=128 * 1024 * 1024,
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_admin(request: HttpRequest) -> AdminAccount | None:
    token = request.COOKIES.get(ADMIN_SESSION_COOKIE)
    if not token:
        return None
    admin_session = AdminSession.objects.select_related("admin").filter(
        token_hash=hash_session_token(token),
        expires_at__gt=timezone.now(),
    ).first()
    return admin_session.admin if admin_session else None


def unauthorized() -> JsonResponse:
    return JsonResponse({"detail": "Admin login required"}, status=401)


def send_email_alert(subject: str, message: str) -> bool:
    if not settings.EMAIL_HOST or not settings.ALERT_EMAIL:
        return False
    try:
        return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [settings.ALERT_EMAIL], fail_silently=False) > 0
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        print(f"Email alert could not be sent: {exc}")
        return False


def home(request: HttpRequest) -> HttpResponse:
    photo_credits = {
        "Mahabodhi Temple": "https://commons.wikimedia.org/wiki/File:Mahabodhitemple.jpg",
        "The Great Buddha Statue": "https://commons.wikimedia.org/wiki/File:Great_Buddha_Statue,_Bodh_Gaya_at_Sunset.jpg",
        "Vishnupad Temple": "https://commons.wikimedia.org/wiki/File:Vishnupad_Temple,Updated.jpg",
        "Nalanda Mahavihara": "https://commons.wikimedia.org/wiki/File:Nalanda,_Buddhist_university_04.jpg",
        "Nalanda Archaeological Museum": "https://commons.wikimedia.org/wiki/File:Nalanda,_Buddhist_university_04.jpg",
        "Rajgir Ropeway & Vishwa Shanti Stupa": "https://commons.wikimedia.org/wiki/File:Shanti_Stupa_at_Rajgir_(cropped).jpg",
        "Griddhakuta Hill": "https://commons.wikimedia.org/wiki/File:Cyclopian_wall,_Rajgir._(5457385482)_(cropped).jpg",
        "Barabar Caves": "https://commons.wikimedia.org/wiki/File:Lomas_Rishi_entrance.jpg",
    }
    place_images = {
        "Mahabodhi Temple": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4e/Mahabodhitemple.jpg/1280px-Mahabodhitemple.jpg",
        "The Great Buddha Statue": "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/bf/Great_Buddha_Statue%2C_Bodh_Gaya_at_Sunset.jpg/1280px-Great_Buddha_Statue%2C_Bodh_Gaya_at_Sunset.jpg",
        "Vishnupad Temple": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/ff/Vishnupad_Temple%2CUpdated.jpg/1280px-Vishnupad_Temple%2CUpdated.jpg",
        "Nalanda Mahavihara": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/09/Nalanda%2C_Buddhist_university_04.jpg/1280px-Nalanda%2C_Buddhist_university_04.jpg",
        "Nalanda Archaeological Museum": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/09/Nalanda%2C_Buddhist_university_04.jpg/1280px-Nalanda%2C_Buddhist_university_04.jpg",
        "Rajgir Ropeway & Vishwa Shanti Stupa": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7f/Shanti_Stupa_at_Rajgir_%28cropped%29.jpg/1280px-Shanti_Stupa_at_Rajgir_%28cropped%29.jpg",
        "Griddhakuta Hill": "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/db/Cyclopian_wall%2C_Rajgir._%285457385482%29_%28cropped%29.jpg/1280px-Cyclopian_wall%2C_Rajgir._%285457385482%29_%28cropped%29.jpg",
        "Barabar Caves": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/25/Lomas_Rishi_entrance.jpg/1280px-Lomas_Rishi_entrance.jpg",
    }
    places = [
        {
            **place_data(place),
            "image": place_images.get(place.name, place.image),
            "credit": photo_credits.get(place.name, ""),
        }
        for place in Place.objects.all()
    ]
    return render(
        request,
        "tourism/home.html",
        {"places": places, "regions": ("Bodh Gaya", "Gaya", "Nalanda", "Rajgir")},
    )


@require_http_methods(["GET"])
def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "Bihar Beyond"})


@csrf_exempt
@require_http_methods(["POST"])
def admin_login(request: HttpRequest) -> JsonResponse:
    data, error = json_body(request)
    if error:
        return error
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
        return JsonResponse({"detail": "Username and password are required"}, status=422)
    account = AdminAccount.objects.filter(username=username.strip().lower()).first()
    if account is None or not verify_password(password, account.password_hash):
        return JsonResponse({"detail": "Invalid username or password"}, status=401)

    token = secrets.token_urlsafe(32)
    AdminSession.objects.create(
        token_hash=hash_session_token(token),
        admin=account,
        expires_at=timezone.now() + ADMIN_SESSION_DURATION,
    )
    response = JsonResponse({"username": account.username})
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=int(ADMIN_SESSION_DURATION.total_seconds()),
        httponly=True,
        secure=request.is_secure(),
        samesite="Strict",
        path="/api",
    )
    return response


@require_http_methods(["GET"])
def admin_session_status(request: HttpRequest) -> JsonResponse:
    admin = current_admin(request)
    return JsonResponse({"username": admin.username}) if admin else unauthorized()


@csrf_exempt
@require_http_methods(["POST"])
def admin_logout(request: HttpRequest) -> HttpResponse:
    token = request.COOKIES.get(ADMIN_SESSION_COOKIE)
    if token:
        AdminSession.objects.filter(token_hash=hash_session_token(token)).delete()
    response = HttpResponse(status=204)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        "",
        max_age=0,
        path="/api",
        httponly=True,
        secure=request.is_secure(),
        samesite="Strict",
    )
    return response


@csrf_exempt
@require_http_methods(["GET", "POST"])
def places(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        query = Place.objects.all()
        region = request.GET.get("region")
        if region:
            query = query.filter(region__icontains=region)
        return JsonResponse([place_data(place) for place in query], safe=False)

    if current_admin(request) is None:
        return unauthorized()
    data, error = json_body(request)
    if error:
        return error
    errors = validate_fields(data, PLACE_FIELDS)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    place = Place.objects.create(**{key: data[key] for key in PLACE_FIELDS})
    return JsonResponse(place_data(place), status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def place_detail(request: HttpRequest, place_id: int) -> JsonResponse | HttpResponse:
    if request.method != "GET" and current_admin(request) is None:
        return unauthorized()
    place = Place.objects.filter(pk=place_id).first()
    if place is None:
        return JsonResponse({"detail": "Place not found"}, status=404)
    if request.method == "GET":
        return JsonResponse(place_data(place))
    if request.method == "DELETE":
        place.delete()
        return HttpResponse(status=204)

    data, error = json_body(request)
    if error:
        return error
    errors = validate_fields(data, PLACE_FIELDS, partial=True)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    for key in PLACE_FIELDS:
        if key in data:
            setattr(place, key, data[key])
    place.save()
    return JsonResponse(place_data(place))


@csrf_exempt
@require_http_methods(["POST"])
def create_inquiry(request: HttpRequest) -> JsonResponse:
    data, error = json_body(request)
    if error:
        return error
    errors = validate_contact(data)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    inquiry = Inquiry.objects.create(name=data["name"], email=data["email"], message=data["message"])
    sent = send_email_alert(
        f"New Bihar Beyond inquiry from {inquiry.name}",
        f"Name: {inquiry.name}\nEmail: {inquiry.email}\n\nMessage:\n{inquiry.message}",
    )
    return JsonResponse(
        {"id": inquiry.id, "message": "Thank you — your message has been received.", "email_sent": sent},
        status=201,
    )


def save_booking(data: dict) -> Booking:
    booking = Booking.objects.create(
        booking_type=data["booking_type"],
        name=data["name"],
        email=data["email"],
        phone=data["phone"],
        destination=data["destination"],
        travel_date=data["travel_date"],
        guests=data.get("guests", 1),
        notes=data.get("notes"),
    )
    send_email_alert(
        f"New {booking.booking_type} request from {booking.name}",
        f"Type: {booking.booking_type}\nName: {booking.name}\nEmail: {booking.email}\nPhone: {booking.phone}\n"
        f"Destination: {booking.destination}\nDate: {booking.travel_date}\nGuests: {booking.guests}\n"
        f"Notes: {booking.notes or '—'}",
    )
    return booking


@csrf_exempt
@require_http_methods(["POST"])
def create_booking(request: HttpRequest) -> JsonResponse:
    data, error = json_body(request)
    if error:
        return error
    errors = validate_contact(data, booking=True)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    return JsonResponse(booking_data(save_booking(data)), status=201)


@csrf_exempt
@require_http_methods(["POST"])
def create_typed_booking(request: HttpRequest, booking_type: str) -> JsonResponse:
    if booking_type not in {"hotel", "cab", "guided"}:
        return JsonResponse({"detail": "Booking type must be hotel, cab or guided"}, status=404)
    data, error = json_body(request)
    if error:
        return error
    errors = validate_contact(data, booking=True)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    if data["booking_type"] != booking_type:
        return JsonResponse({"detail": "Booking type in the URL and request body must match"}, status=422)
    return JsonResponse(booking_data(save_booking(data)), status=201)


@require_http_methods(["GET"])
def admin_inquiries(request: HttpRequest) -> JsonResponse:
    if current_admin(request) is None:
        return unauthorized()
    inquiries = Inquiry.objects.order_by("-created_at")[:200]
    return JsonResponse(
        [{"id": item.id, "name": item.name, "email": item.email, "message": item.message} for item in inquiries],
        safe=False,
    )


@require_http_methods(["GET"])
def admin_bookings(request: HttpRequest) -> JsonResponse:
    if current_admin(request) is None:
        return unauthorized()
    bookings = Booking.objects.order_by("-created_at")[:200]
    return JsonResponse(
        [
            {
                **booking_data(item),
                "email": item.email,
                "phone": item.phone,
                "guests": item.guests,
                "notes": item.notes,
            }
            for item in bookings
        ],
        safe=False,
    )
