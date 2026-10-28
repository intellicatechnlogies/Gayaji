import base64
import binascii
import hashlib
import json
import logging
import secrets
from datetime import timedelta
from json import JSONDecodeError
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .locations import STATE_CITIES
from .models import (
    AdminAccount,
    AdminSession,
    Booking,
    CityPincode,
    Guide,
    GuideLanguage,
    Hotel,
    HotelLocation,
    Inquiry,
    Place,
    PlanningRequest,
    Restaurant,
    StoredCredential,
    StoredCredentialApiUser,
    Van,
)
from .credential_vault import decrypt_credential, encrypt_credential
from .email_utils import queue_notification_email, send_notification_email
from .s3_storage import (
    S3StorageError,
    delete_place_image,
    get_place_image_url,
    prepare_place_image,
    upload_place_image,
)
from cryptography.fernet import InvalidToken

ADMIN_SESSION_COOKIE = "beyond_admin_session"
ADMIN_SESSION_DURATION = timedelta(hours=12)
BOOKING_DESTINATIONS = ("Bodh Gaya", "Gaya", "Nalanda", "Rajgir")
BOOKING_TYPES = {
    "complete-trip": "Plan my complete trip",
    "hotel": "Hotel / accommodation",
    "cab": "Cab / private van",
    "guided": "Guided visit",
}
ARRANGEMENT_OPTIONS = {
    "complete-trip": "Plan my complete trip",
    "accommodation": "Accommodation / stay",
    "private-van": "Private van or cab",
    "guided-visits": "Guided visits and tours",
    "custom": "Something else",
}
logger = logging.getLogger(__name__)
PLACE_FIELDS = {
    "name": (2, 160),
    "description": (10, None),
    "region": (2, 100),
    "category": (2, 100),
}
ADMIN_LISTING_MODELS = {
    "hotels": Hotel,
    "restaurants": Restaurant,
    "vans": Van,
    "guides": Guide,
}
POSTAL_CITY_QUERY_ALIASES = {
    "Bodh Gaya": "Bodhgaya",
    "Cherrapunji": "Sohra",
    "Chhatrapati Sambhajinagar": "Aurangabad",
    "Ooty": "Udagamandalam",
    "Sri Vijaya Puram": "Port Blair",
}
POSTAL_DISTRICT_ALIASES = {
    "Bodh Gaya": "Gaya",
    "Cherrapunji": "East Khasi Hills",
    "Chhatrapati Sambhajinagar": "Aurangabad",
    "Ooty": "Nilgiris",
    "Rajgir": "Nalanda",
    "Sri Vijaya Puram": "South Andaman",
}


def json_body(request: HttpRequest) -> tuple[dict | None, JsonResponse | None]:
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Request body must be valid JSON"}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"detail": "Request body must be a JSON object"}, status=400)
    return data, None


def multipart_form_data(request: HttpRequest) -> tuple[dict, UploadedFile | None]:
    if request.method == "POST":
        return request.POST.dict(), request.FILES.get("image")
    data, files = MultiPartParser(
        request.META,
        request,
        request.upload_handlers,
        request.encoding,
    ).parse()
    return data.dict(), files.get("image")


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
        raw_destinations = data.get("destinations", data.get("destination"))
        if isinstance(raw_destinations, str):
            requested_destinations = raw_destinations.split(",")
        elif isinstance(raw_destinations, list):
            requested_destinations = raw_destinations
        else:
            requested_destinations = []
        destination_lookup = {region.casefold(): region for region in BOOKING_DESTINATIONS}
        normalized_destinations = []
        has_invalid_destination = not requested_destinations
        for destination in requested_destinations:
            if not isinstance(destination, str):
                has_invalid_destination = True
                continue
            normalized = destination.strip()
            canonical = destination_lookup.get(normalized.casefold())
            if canonical is None:
                has_invalid_destination = True
            elif canonical not in normalized_destinations:
                normalized_destinations.append(canonical)
        data["destination"] = ", ".join(normalized_destinations)
        data.pop("destinations", None)
        if (
            has_invalid_destination
            or not normalized_destinations
            or len(data["destination"]) > 160
        ):
            errors["destination"] = "Select one or more valid destinations."
        raw_booking_types = data.get("booking_types", data.get("booking_type"))
        if isinstance(raw_booking_types, str):
            requested_booking_types = [raw_booking_types]
        elif isinstance(raw_booking_types, list):
            requested_booking_types = raw_booking_types
        else:
            requested_booking_types = []
        normalized_booking_types = []
        for booking_type in requested_booking_types:
            if not isinstance(booking_type, str) or booking_type not in BOOKING_TYPES:
                errors["booking_type"] = "Select one or more valid services."
                continue
            if booking_type not in normalized_booking_types:
                normalized_booking_types.append(booking_type)
        if not normalized_booking_types:
            errors["booking_type"] = "Select one or more services."
        data["booking_type"] = ", ".join(normalized_booking_types)
        data.pop("booking_types", None)
        guests = data.get("guests", 1)
        if isinstance(guests, bool) or not isinstance(guests, int) or not 1 <= guests <= 30:
            errors["guests"] = "Must be a whole number between 1 and 30."
        notes = data.get("notes")
        if notes is not None and (not isinstance(notes, str) or len(notes) > 2000):
            errors["notes"] = "Must be text of no more than 2000 characters."
    else:
        raw_arrangements = data.get("arrangements", data.get("service"))
        if isinstance(raw_arrangements, str):
            requested_arrangements = [raw_arrangements]
        elif isinstance(raw_arrangements, list):
            requested_arrangements = raw_arrangements
        else:
            requested_arrangements = []
        normalized_arrangements = []
        for arrangement in requested_arrangements:
            if not isinstance(arrangement, str) or arrangement not in ARRANGEMENT_OPTIONS:
                errors["arrangements"] = "Select one or more valid arrangements."
                continue
            if arrangement not in normalized_arrangements:
                normalized_arrangements.append(arrangement)
        if not normalized_arrangements:
            errors["arrangements"] = "Select one or more arrangements."
        data["arrangements"] = normalized_arrangements
        data.pop("service", None)
    return errors


def place_data(place: Place) -> dict:
    return {
        "id": place.id,
        "name": place.name,
        "description": place.description,
        "image": reverse("place-image", kwargs={"place_id": place.id}),
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


def home(request: HttpRequest, admin_page: bool = False) -> HttpResponse:
    places = [place_data(place) for place in Place.objects.all()]
    state_cities = {state: set(cities) for state, cities in STATE_CITIES.items()}
    for location in CityPincode.objects.values("state", "city").distinct():
        state_cities.setdefault(location["state"], set()).add(location["city"])
    guide_languages = GuideLanguage.objects.values_list("name", flat=True)

    return render(
        request,
        "tourism/home.html",
        {
            "places": places,
            "regions": BOOKING_DESTINATIONS,
            "state_cities": {
                state: sorted(cities, key=str.casefold)
                for state, cities in state_cities.items()
            },
            "guide_languages": guide_languages,
            "van_types": Van.VEHICLE_TYPES,
            "admin_page": admin_page,
        },
    )


def admin_page(request: HttpRequest) -> HttpResponse:
    return home(request, admin_page=True)


def get_or_create_guide_language(name: str) -> GuideLanguage:
    language = GuideLanguage.objects.filter(name__iexact=name).first()
    if language:
        return language
    try:
        with transaction.atomic():
            return GuideLanguage.objects.create(name=name)
    except IntegrityError:
        return GuideLanguage.objects.get(name__iexact=name)


@require_http_methods(["GET"])
def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "Bihar Beyond"})


def normalize_location(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def fetch_location_pincodes(state: str, city: str) -> list[str]:
    cache_key = f"tourism:location-pincodes:{quote(state, safe='')}:{quote(city, safe='')}"
    saved_pincodes = list(
        CityPincode.objects.filter(state__iexact=state, city__iexact=city)
        .values_list("postal_code", flat=True)
    )
    cached_pincodes = cache.get(cache_key)
    if cached_pincodes is not None:
        return sorted(set(cached_pincodes) | set(saved_pincodes))

    if city not in STATE_CITIES.get(state, ()) and saved_pincodes:
        return sorted(set(saved_pincodes))

    postal_city = POSTAL_CITY_QUERY_ALIASES.get(city, city)
    query = quote(postal_city, safe="")
    try:
        with urlopen(f"https://api.postalpincode.in/postoffice/{query}", timeout=10) as response:
            postal_data = json.loads(response.read())
    except (OSError, URLError, JSONDecodeError, UnicodeDecodeError):
        if saved_pincodes:
            return sorted(set(saved_pincodes))
        raise

    if (
        not isinstance(postal_data, list)
        or not postal_data
        or not isinstance(postal_data[0], dict)
        or postal_data[0].get("Status") != "Success"
        or not isinstance(postal_data[0].get("PostOffice"), list)
    ):
        return sorted(set(saved_pincodes))

    normalized_city = normalize_location(city)
    normalized_postal_city = normalize_location(postal_city)
    normalized_district = normalize_location(POSTAL_DISTRICT_ALIASES.get(city, city))

    def matches_location(office: dict) -> bool:
        office_state = office.get("State")
        office_name = office.get("Name")
        office_district = office.get("District")
        pincode = office.get("Pincode")
        return (
            isinstance(office_state, str)
            and normalize_location(office_state) == normalize_location(state)
            and (
                isinstance(office_district, str)
                and normalize_location(office_district) == normalized_district
                or isinstance(office_name, str)
                and normalize_location(office_name) in {normalized_city, normalized_postal_city}
            )
            and isinstance(pincode, str)
            and len(pincode) == 6
            and pincode.isdigit()
        )

    pincodes = sorted(
        {
            office["Pincode"]
            for office in postal_data[0]["PostOffice"]
            if isinstance(office, dict)
            and matches_location(office)
        }
    )
    cache.set(cache_key, pincodes, timeout=86400)
    return sorted(set(pincodes) | set(saved_pincodes))


@require_http_methods(["GET"])
def location_pincodes(request: HttpRequest) -> JsonResponse:
    if current_admin(request) is None:
        return unauthorized()
    state = request.GET.get("state", "")
    city = request.GET.get("city", "")
    if state not in STATE_CITIES:
        return JsonResponse({"detail": "Select a valid state and city."}, status=422)
    if (
        city not in STATE_CITIES[state]
        and not CityPincode.objects.filter(state__iexact=state, city__iexact=city).exists()
    ):
        return JsonResponse({"detail": "Select a valid state and city."}, status=422)

    try:
        pincodes = fetch_location_pincodes(state, city)
    except (OSError, URLError, JSONDecodeError, UnicodeDecodeError) as exc:
        return JsonResponse({"detail": f"PIN-code directory is unavailable: {exc}"}, status=502)
    if not pincodes:
        return JsonResponse({"detail": "No PIN codes were found for that city."}, status=404)
    return JsonResponse(pincodes, safe=False)


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
    if request.content_type.startswith("multipart/form-data"):
        try:
            data, image_file = multipart_form_data(request)
        except MultiPartParserError:
            return JsonResponse({"detail": "Invalid multipart form data."}, status=400)
    else:
        data, error = json_body(request)
        if error:
            return error
        image_file = None
    data = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in data.items()
    }
    errors = validate_fields(data, PLACE_FIELDS)
    if image_file is None:
        errors["image"] = "An image upload is required."
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    try:
        image = prepare_place_image(image_file)
        with transaction.atomic():
            place = Place.objects.create(**{key: data[key] for key in PLACE_FIELDS})
            upload_place_image(place.id, *image)
    except ValueError as exc:
        return JsonResponse({"detail": {"image": str(exc)}}, status=422)
    except S3StorageError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
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
        try:
            delete_place_image(place.id)
        except S3StorageError as exc:
            return JsonResponse({"detail": str(exc)}, status=503)
        place.delete()
        return HttpResponse(status=204)

    if request.content_type.startswith("multipart/form-data"):
        try:
            data, image_file = multipart_form_data(request)
        except MultiPartParserError:
            return JsonResponse({"detail": "Invalid multipart form data."}, status=400)
    else:
        data, error = json_body(request)
        if error:
            return error
        image_file = None
    data = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in data.items()
    }
    errors = validate_fields(data, PLACE_FIELDS, partial=True)
    if not data and image_file is None:
        errors["detail"] = "Provide fields or an image to update."
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    for key in PLACE_FIELDS:
        if key in data:
            setattr(place, key, data[key])
    try:
        if image_file is not None:
            image = prepare_place_image(image_file)
            upload_place_image(place.id, *image)
        if data:
            place.save()
    except ValueError as exc:
        return JsonResponse({"detail": {"image": str(exc)}}, status=422)
    except S3StorageError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
    return JsonResponse(place_data(place))


@require_http_methods(["GET"])
def place_image(request: HttpRequest, place_id: int) -> HttpResponse:
    if not Place.objects.filter(pk=place_id).exists():
        return JsonResponse({"detail": "Place not found"}, status=404)
    try:
        image_url = get_place_image_url(place_id)
    except S3StorageError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
    if image_url is None:
        return JsonResponse({"detail": "Place image not found"}, status=404)
    return HttpResponseRedirect(image_url)


@csrf_exempt
@require_http_methods(["POST"])
def create_inquiry(request: HttpRequest) -> JsonResponse:
    data, error = json_body(request)
    if error:
        return error
    errors = validate_contact(data)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    arrangements = "\n".join(
        f"- {ARRANGEMENT_OPTIONS[key]}" for key in data["arrangements"]
    )
    message = f"Requested arrangements:\n{arrangements}\n\n{data['message']}"
    try:
        with transaction.atomic():
            inquiry = Inquiry.objects.create(name=data["name"], email=data["email"], message=message)
            PlanningRequest.objects.create(
                request_type="inquiry",
                name=data["name"],
                email=data["email"],
                arrangements=", ".join(
                    ARRANGEMENT_OPTIONS[key] for key in data["arrangements"]
                ),
                message=data["message"],
            )
            queue_notification_email(
                f"New Bihar Beyond inquiry from {data['name']}",
                f"Name: {data['name']}\nEmail: {data['email']}\n\n{message}",
            )
    except CommandError:
        logger.exception("Could not queue contact inquiry email.")
        return JsonResponse(
            {"detail": "Your message could not be queued. Please try again later."},
            status=503,
        )
    return JsonResponse(
        {"id": inquiry.id, "message": "Thank you — your message has been received.", "email_queued": True},
        status=201,
    )


def save_booking(data: dict) -> Booking:
    return Booking.objects.create(
        booking_type=data["booking_type"],
        name=data["name"],
        email=data["email"],
        phone=data["phone"],
        destination=data["destination"],
        travel_date=data["travel_date"],
        guests=data.get("guests", 1),
        notes=data.get("notes"),
    )


def booking_notification_content(data: dict) -> tuple[str, str]:
    service_labels = ", ".join(
        BOOKING_TYPES.get(value, value) for value in data["booking_type"].split(", ")
    )
    return (
        f"New trip request from {data['name']}",
        (
            f"Services: {service_labels}\nName: {data['name']}\nEmail: {data['email']}\n"
            f"Phone: {data['phone']}\nDestination: {data['destination']}\n"
            f"Date: {data['travel_date']}\nGuests: {data.get('guests', 1)}\n"
            f"Notes: {data.get('notes') or '—'}"
        ),
    )


def send_booking_notification(data: dict) -> None:
    send_notification_email(*booking_notification_content(data))


def create_booking_response(data: dict) -> JsonResponse:
    try:
        with transaction.atomic():
            booking = save_booking(data)
            PlanningRequest.objects.create(
                request_type="trip",
                name=data["name"],
                email=data["email"],
                phone=data["phone"],
                services=", ".join(
                    BOOKING_TYPES[value] for value in data["booking_type"].split(", ")
                ),
                destinations=data["destination"],
                travel_date=data["travel_date"],
                guests=data.get("guests", 1),
                message=data.get("notes") or "",
            )
            queue_notification_email(*booking_notification_content(data))
    except CommandError:
        logger.exception("Could not queue travel request email.")
        return JsonResponse(
            {"detail": "The travel request could not be queued. Please try again later."},
            status=503,
        )
    return JsonResponse(booking_data(booking), status=201)


def planning_request_data(item: PlanningRequest) -> dict:
    return {
        "id": item.id,
        "request_type": item.request_type,
        "name": item.name,
        "email": item.email,
        "phone": item.phone,
        "arrangements": item.arrangements,
        "services": item.services,
        "destinations": item.destinations,
        "travel_date": item.travel_date,
        "guests": item.guests,
        "message": item.message,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@require_http_methods(["GET"])
def admin_planning_requests(request: HttpRequest) -> JsonResponse:
    if current_admin(request) is None:
        return unauthorized()
    requests = PlanningRequest.objects.all()[:500]
    return JsonResponse(
        [planning_request_data(item) for item in requests],
        safe=False,
        encoder=DjangoJSONEncoder,
    )


@csrf_exempt
@require_http_methods(["PATCH", "PUT", "DELETE"])
def admin_planning_request_detail(request: HttpRequest, request_id: int) -> HttpResponse:
    if current_admin(request) is None:
        return unauthorized()
    item = PlanningRequest.objects.filter(pk=request_id).first()
    if item is None:
        return JsonResponse({"detail": "Planning request not found"}, status=404)
    if request.method == "DELETE":
        item.delete()
        return HttpResponse(status=204)

    data, error = json_body(request)
    if error:
        return error
    fields = {
        "request_type": (item, "request_type", 20),
        "name": (item, "name", 160),
        "email": (item, "email", 254),
        "phone": (item, "phone", 40),
        "arrangements": (item, "arrangements", None),
        "services": (item, "services", None),
        "destinations": (item, "destinations", 160),
        "travel_date": (item, "travel_date", 30),
        "message": (item, "message", None),
    }
    allowed_fields = set(fields) | {"guests"}
    if not data or set(data) - allowed_fields:
        return JsonResponse({"detail": "Provide valid planning request fields."}, status=422)
    errors = {}
    for field, value in data.items():
        if field == "guests":
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 30
            ):
                errors[field] = "Must be a whole number between 1 and 30."
            else:
                item.guests = value
            continue
        if not isinstance(value, str):
            errors[field] = "Must be text."
            continue
        instance, attribute, maximum = fields[field]
        normalized = value.strip()
        if field in {"name", "email"} and not normalized:
            errors[field] = "This field is required."
            continue
        if maximum is not None and len(normalized) > maximum:
            errors[field] = f"Must be no more than {maximum} characters."
            continue
        setattr(instance, attribute, normalized)
    if "request_type" in data and item.request_type not in {"trip", "inquiry"}:
        errors["request_type"] = "Must be trip or inquiry."
    if "email" in data and "email" not in errors:
        try:
            validate_email(item.email)
        except ValidationError:
            errors["email"] = "Enter a valid email address."
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    item.save()
    return JsonResponse(planning_request_data(item), encoder=DjangoJSONEncoder)


@csrf_exempt
@require_http_methods(["POST"])
def create_booking(request: HttpRequest) -> JsonResponse:
    data, error = json_body(request)
    if error:
        return error
    errors = validate_contact(data, booking=True)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    return create_booking_response(data)


@csrf_exempt
@require_http_methods(["POST"])
def create_typed_booking(request: HttpRequest, booking_type: str) -> JsonResponse:
    if booking_type not in BOOKING_TYPES:
        return JsonResponse({"detail": "Booking type must be hotel, cab or guided"}, status=404)
    data, error = json_body(request)
    if error:
        return error
    errors = validate_contact(data, booking=True)
    if errors:
        return JsonResponse({"detail": errors}, status=422)
    if data["booking_type"] != booking_type:
        return JsonResponse({"detail": "Booking type in the URL and request body must match"}, status=422)
    return create_booking_response(data)


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


@csrf_exempt
@require_http_methods(["GET", "POST"])
def admin_credentials(request: HttpRequest) -> JsonResponse:
    if current_admin(request) is None:
        return unauthorized()
    if request.method == "GET":
        return JsonResponse(
            [
                {
                    "id": item.id,
                    "service": item.service,
                    "name": item.name,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in StoredCredential.objects.all()
            ],
            safe=False,
        )

    data, error = json_body(request)
    if error:
        return error
    if set(data) != {"service", "name", "secret"}:
        return JsonResponse({"detail": "Provide service, credential name and secret."}, status=422)
    service = data.get("service")
    name = data.get("name")
    secret = data.get("secret")
    if not isinstance(service, str) or not service.strip() or len(service.strip()) > 100:
        return JsonResponse({"detail": {"service": "Enter a service name of up to 100 characters."}}, status=422)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return JsonResponse({"detail": {"name": "Enter a credential name of up to 120 characters."}}, status=422)
    if not isinstance(secret, str) or not secret.strip() or len(secret) > 10000:
        return JsonResponse({"detail": {"secret": "Enter a non-empty secret of up to 10000 characters."}}, status=422)
    encrypted_secret = encrypt_credential(secret)
    credential, _ = StoredCredential.objects.update_or_create(
        service=service.strip(),
        name=name.strip(),
        defaults={"encrypted_secret": encrypted_secret},
    )
    return JsonResponse(
        {
            "id": credential.id,
            "service": credential.service,
            "name": credential.name,
            "updated_at": credential.updated_at.isoformat(),
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["DELETE"])
def admin_credential_detail(request: HttpRequest, credential_id: int) -> HttpResponse:
    if current_admin(request) is None:
        return unauthorized()
    deleted, _ = StoredCredential.objects.filter(id=credential_id).delete()
    return HttpResponse(status=204 if deleted else 404)


def stored_credentials_api_user(request: HttpRequest) -> StoredCredentialApiUser | None:
    authorization = request.headers.get("Authorization", "")
    scheme, _, encoded_credentials = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded_credentials:
        return None
    try:
        decoded_credentials = base64.b64decode(encoded_credentials, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, separator, password = decoded_credentials.partition(":")
    if not separator:
        return None
    api_user = StoredCredentialApiUser.objects.filter(username=username).first()
    if api_user is None or not check_password(password, api_user.password_hash):
        return None
    return api_user


def stored_credentials_api_unauthorized() -> JsonResponse:
    response = JsonResponse({"detail": "Valid API Basic credentials are required."}, status=401)
    response["WWW-Authenticate"] = 'Basic realm="Stored credentials API"'
    return response


@csrf_exempt
@require_http_methods(["GET", "POST"])
def stored_credentials_api(request: HttpRequest) -> JsonResponse:
    if stored_credentials_api_user(request) is None:
        return stored_credentials_api_unauthorized()

    if request.method == "GET":
        credentials = StoredCredential.objects.all()
        service = request.GET.get("service")
        if service:
            credentials = credentials.filter(service__iexact=service)
        try:
            values = [
                {
                    "id": item.id,
                    "service": item.service,
                    "name": item.name,
                    "value": decrypt_credential(item.encrypted_secret),
                    "updated_at": item.updated_at.isoformat(timespec="seconds"),
                }
                for item in credentials
            ]
        except (InvalidToken, UnicodeDecodeError) as exc:
            return JsonResponse({"detail": f"Stored credentials could not be decrypted: {exc}"}, status=503)
        return JsonResponse(values, safe=False)

    data, error = json_body(request)
    if error:
        return error
    if set(data) != {"service", "name", "value"}:
        return JsonResponse({"detail": "Provide service, credential name and plaintext value."}, status=422)
    service = data.get("service")
    name = data.get("name")
    value = data.get("value")
    if not isinstance(service, str) or not service.strip() or len(service.strip()) > 100:
        return JsonResponse({"detail": {"service": "Enter a service name of up to 100 characters."}}, status=422)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return JsonResponse({"detail": {"name": "Enter a credential name of up to 120 characters."}}, status=422)
    if not isinstance(value, str) or not value.strip() or len(value) > 10000:
        return JsonResponse({"detail": {"value": "Enter a non-empty plaintext value of up to 10000 characters."}}, status=422)
    encrypted_secret = encrypt_credential(value)
    credential, _ = StoredCredential.objects.update_or_create(
        service=service.strip(),
        name=name.strip(),
        defaults={"encrypted_secret": encrypted_secret},
    )
    return JsonResponse(
        {
            "id": credential.id,
            "service": credential.service,
            "name": credential.name,
            "updated_at": credential.updated_at.isoformat(timespec="seconds"),
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["DELETE"])
def stored_credentials_api_detail(request: HttpRequest, credential_id: int) -> HttpResponse:
    if stored_credentials_api_user(request) is None:
        return stored_credentials_api_unauthorized()
    deleted, _ = StoredCredential.objects.filter(id=credential_id).delete()
    return HttpResponse(status=204 if deleted else 404)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def admin_listings(request: HttpRequest, listing_type: str) -> JsonResponse:
    model = ADMIN_LISTING_MODELS.get(listing_type)
    if model is None:
        return JsonResponse({"detail": "Listing type must be hotels, restaurants, vans or guides"}, status=404)
    if current_admin(request) is None:
        return unauthorized()
    if request.method == "GET":
        if listing_type == "hotels":
            return JsonResponse(
                [
                    {
                        "id": item.id,
                        "name": item.name,
                        "website": item.website,
                        "air_conditioning": item.air_conditioning,
                        "price_range": item.price_range,
                        "star_rating": item.star_rating,
                        "locations": [
                            {
                                "state": location.state,
                                "city": location.city,
                                "postal_code": location.postal_code,
                                "contact_info": location.contact_info,
                                "address": location.address,
                            }
                            for location in item.locations.all()
                        ],
                    }
                    for item in Hotel.objects.prefetch_related("locations")
                ],
                safe=False,
            )

    if listing_type == "hotels" and request.method == "POST":
        data, error = json_body(request)
        if error:
            return error
        locations = data.pop("locations", None)
        required_fields = {"name", "air_conditioning", "price_range", "star_rating"}
        if (
            not required_fields.issubset(data)
            or set(data) - required_fields - {"website"}
            or not isinstance(locations, list)
            or not locations
        ):
            return JsonResponse({"detail": "Provide hotel details and at least one branch location."}, status=422)
        hotel = Hotel(**data)
        try:
            hotel.full_clean()
        except ValidationError as exc:
            return JsonResponse({"detail": exc.message_dict}, status=422)

        location_fields = {"state", "city", "postal_code", "contact_info", "address"}
        validated_locations = []
        custom_locations = []
        for location_data in locations:
            if not isinstance(location_data, dict):
                return JsonResponse({"detail": "Each hotel location must be an object."}, status=422)
            postal_code_is_other = location_data.pop("postal_code_is_other", False)
            city_is_other = location_data.pop("city_is_other", False)
            if not isinstance(postal_code_is_other, bool) or not isinstance(city_is_other, bool):
                return JsonResponse({"detail": "Location option flags must be true or false."}, status=422)
            if set(location_data) != location_fields:
                return JsonResponse({"detail": "Each branch must include state, city, PIN, contact and address."}, status=422)
            state = location_data.get("state")
            city = location_data.get("city")
            if not isinstance(state, str) or state not in STATE_CITIES:
                return JsonResponse({"detail": {"state": "Select a valid state."}}, status=422)
            if not isinstance(city_is_other, bool):
                return JsonResponse({"detail": {"city": "Select a listed city or choose Other."}}, status=422)
            if not isinstance(city, str) or not city.strip() or len(city.strip()) > 100:
                return JsonResponse({"detail": {"city": "Enter a valid city."}}, status=422)
            location_data["city"] = city.strip()
            location = HotelLocation(**location_data)
            try:
                location.full_clean(exclude=("hotel",))
            except ValidationError as exc:
                return JsonResponse({"detail": exc.message_dict}, status=422)
            known_city = city in STATE_CITIES[state] or CityPincode.objects.filter(
                state__iexact=state, city__iexact=location.city
            ).exists()
            if not known_city and not city_is_other:
                return JsonResponse({"detail": {"city": "Select a listed city or choose Other."}}, status=422)
            if known_city and not postal_code_is_other:
                try:
                    pincodes = fetch_location_pincodes(state, location.city)
                except (OSError, URLError, JSONDecodeError, UnicodeDecodeError) as exc:
                    return JsonResponse({"detail": f"PIN-code directory is unavailable: {exc}"}, status=502)
                if location.postal_code not in pincodes:
                    return JsonResponse(
                        {"detail": {"postal_code": "Select a PIN code listed for the selected state and city."}},
                        status=422,
                    )
            validated_locations.append(location)
            if city_is_other or postal_code_is_other:
                custom_locations.append((state, location.city, location.postal_code))

        with transaction.atomic():
            hotel.save()
            for location in validated_locations:
                location.hotel = hotel
                location.save()
            for state, city, postal_code in custom_locations:
                CityPincode.objects.get_or_create(state=state, city=city, postal_code=postal_code)
        return JsonResponse(
            {
                "id": hotel.id,
                "name": hotel.name,
                "website": hotel.website,
                "air_conditioning": hotel.air_conditioning,
                "price_range": hotel.price_range,
                "star_rating": hotel.star_rating,
                "locations": [
                    {
                        "state": location.state,
                        "city": location.city,
                        "postal_code": location.postal_code,
                        "contact_info": location.contact_info,
                        "address": location.address,
                    }
                    for location in hotel.locations.all()
                ],
            },
            status=201,
        )

    if request.method == "GET":
        fields = [
            field.name
            for field in model._meta.concrete_fields
            if not (listing_type == "vans" and field.name == "price_range")
        ]
        return JsonResponse(
            [{field: getattr(item, field) for field in fields} for item in model.objects.all()],
            safe=False,
        )

    data, error = json_body(request)
    if error:
        return error
    postal_code_is_other = data.pop("postal_code_is_other", False)
    city_is_other = data.pop("city_is_other", False)
    if not isinstance(postal_code_is_other, bool) or not isinstance(city_is_other, bool):
        return JsonResponse({"detail": "Location option flags must be true or false."}, status=422)
    fields = {
        field.name
        for field in model._meta.concrete_fields
        if field.name not in {"id", "created_at"}
        and not (listing_type == "vans" and field.name == "price_range")
    }
    if set(data) != fields:
        return JsonResponse({"detail": "Please provide all required listing fields."}, status=422)
    if listing_type == "vans" and any(
        data.get(field) in (None, "")
        for field in ("booking_charge_per_day", "per_km_charge")
    ):
        return JsonResponse(
            {"detail": "Provide both the daily booking charge and per-kilometre charge."},
            status=422,
        )
    guide_languages = []
    if listing_type == "guides":
        submitted_languages = data.get("languages")
        if not isinstance(submitted_languages, str):
            return JsonResponse({"detail": {"languages": "Select at least one language."}}, status=422)
        seen_languages = set()
        for language_name in submitted_languages.split(","):
            language_name = language_name.strip()
            normalized_name = language_name.casefold()
            if language_name and normalized_name not in seen_languages:
                if len(language_name) > 100:
                    return JsonResponse(
                        {"detail": {"languages": "Each language must be 100 characters or fewer."}},
                        status=422,
                    )
                seen_languages.add(normalized_name)
                guide_languages.append(language_name)
        if not guide_languages:
            return JsonResponse({"detail": {"languages": "Select at least one language."}}, status=422)
        data["languages"] = ", ".join(guide_languages)
    if "state" in fields:
        state = data["state"]
        city = data["city"]
        if not isinstance(state, str) or state not in STATE_CITIES:
            return JsonResponse({"detail": {"state": "Select a valid state."}}, status=422)
        if not isinstance(city, str) or not city.strip() or len(city.strip()) > 100:
            return JsonResponse({"detail": {"city": "Enter a valid city."}}, status=422)
        city = city.strip()
        data["city"] = city
    item = model(**data)
    try:
        item.full_clean()
    except ValidationError as exc:
        return JsonResponse({"detail": exc.message_dict}, status=422)
    if "state" in fields:
        if len(item.postal_code) != 6 or not item.postal_code.isdigit():
            return JsonResponse({"detail": {"postal_code": "Enter a valid 6-digit PIN code."}}, status=422)
        known_city = city in STATE_CITIES[state] or CityPincode.objects.filter(
            state__iexact=state, city__iexact=city
        ).exists()
        if known_city and not postal_code_is_other:
            try:
                pincodes = fetch_location_pincodes(state, city)
            except (OSError, URLError, JSONDecodeError, UnicodeDecodeError) as exc:
                return JsonResponse({"detail": f"PIN-code directory is unavailable: {exc}"}, status=502)
            if item.postal_code not in pincodes:
                return JsonResponse(
                    {"detail": {"postal_code": "Select a PIN code listed for the selected state and city."}},
                    status=422,
                )
    with transaction.atomic():
        for language_name in guide_languages:
            get_or_create_guide_language(language_name)
        item.save()
        if city_is_other or postal_code_is_other:
            CityPincode.objects.get_or_create(
                state=item.state,
                city=item.city,
                postal_code=item.postal_code,
            )
    return JsonResponse(
        {field: getattr(item, field) for field in ("id", *fields, "created_at")},
        status=201,
        encoder=DjangoJSONEncoder,
    )


@csrf_exempt
@require_http_methods(["DELETE"])
def admin_listing_detail(request: HttpRequest, listing_type: str, listing_id: int) -> HttpResponse:
    model = ADMIN_LISTING_MODELS.get(listing_type)
    if model is None:
        return JsonResponse({"detail": "Listing type must be hotels, restaurants, vans or guides"}, status=404)
    if current_admin(request) is None:
        return unauthorized()
    item = model.objects.filter(pk=listing_id).first()
    if item is None:
        return JsonResponse({"detail": "Listing not found"}, status=404)
    item.delete()
    return HttpResponse(status=204)
