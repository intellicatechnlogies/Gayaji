import getpass

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tourism.models import AdminAccount, AdminSession, Place
from tourism.views import hash_password

SEED_PLACES = [
    {
        "name": "Mahabodhi Temple",
        "description": "A UNESCO World Heritage Site marking the place where Siddhartha Gautama attained enlightenment beneath the Bodhi Tree. Explore its serene gardens, sacred pond and soaring stone temple.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/4e/Mahabodhitemple.jpg/1280px-Mahabodhitemple.jpg",
        "region": "Bodh Gaya",
        "category": "Sacred heritage",
    },
    {
        "name": "The Great Buddha Statue",
        "description": "A peaceful 80-foot monument surrounded by a meditative garden, with smaller statues depicting scenes from the Buddha's life along the pathway.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/bf/Great_Buddha_Statue%2C_Bodh_Gaya_at_Sunset.jpg/1280px-Great_Buddha_Statue%2C_Bodh_Gaya_at_Sunset.jpg",
        "region": "Bodh Gaya",
        "category": "Spiritual landmark",
    },
    {
        "name": "Vishnupad Temple",
        "description": "An important riverside pilgrimage site in Gaya, known for its distinctive shikhara and the sacred footprint believed to be that of Lord Vishnu.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/ff/Vishnupad_Temple%2CUpdated.jpg/1280px-Vishnupad_Temple%2CUpdated.jpg",
        "region": "Gaya",
        "category": "Temple & culture",
    },
    {
        "name": "Nalanda Mahavihara",
        "description": "Walk through the evocative red-brick remains of one of the world's earliest residential universities, a celebrated UNESCO World Heritage Site.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/09/Nalanda%2C_Buddhist_university_04.jpg/1280px-Nalanda%2C_Buddhist_university_04.jpg",
        "region": "Nalanda",
        "category": "UNESCO heritage",
    },
    {
        "name": "Rajgir Ropeway & Vishwa Shanti Stupa",
        "description": "Ride above forested hills to a gleaming peace pagoda, with sweeping views over Rajgir's green valleys and ancient landscape.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7f/Shanti_Stupa_at_Rajgir_%28cropped%29.jpg/1280px-Shanti_Stupa_at_Rajgir_%28cropped%29.jpg",
        "region": "Rajgir",
        "category": "Hill escape",
    },
    {
        "name": "Griddhakuta Hill",
        "description": "Known as Vulture's Peak, this tranquil hilltop is associated with the Buddha's teachings and rewards visitors with beautiful valley views.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/db/Cyclopian_wall%2C_Rajgir._%285457385482%29_%28cropped%29.jpg/1280px-Cyclopian_wall%2C_Rajgir._%285457385482%29_%28cropped%29.jpg",
        "region": "Rajgir",
        "category": "Nature & spirituality",
    },
    {
        "name": "Barabar Caves",
        "description": "Discover India's oldest surviving rock-cut caves, remarkable for their polished granite interiors and ancient inscriptions.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/25/Lomas_Rishi_entrance.jpg/1280px-Lomas_Rishi_entrance.jpg",
        "region": "Gaya",
        "category": "Ancient history",
    },
    {
        "name": "Nalanda Archaeological Museum",
        "description": "See sculptures, inscriptions and finds from the ancient university site in a compact museum just across the road from the ruins.",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/09/Nalanda%2C_Buddhist_university_04.jpg/1280px-Nalanda%2C_Buddhist_university_04.jpg",
        "region": "Nalanda",
        "category": "Museum",
    },
]


class Command(BaseCommand):
    help = "Seed sample attractions and interactively create the initial admin when needed."

    def handle(self, *args, **options):
        if not AdminAccount.objects.exists():
            username = input("Admin username: ").strip().lower()
            if not username:
                raise CommandError("Admin username cannot be empty.")
            password = getpass.getpass("Admin password (at least 6 characters): ")
            confirmation = getpass.getpass("Confirm admin password: ")
            if password != confirmation:
                raise CommandError("Admin passwords do not match.")
            if len(password) < 6:
                raise CommandError("Admin password must be at least 6 characters.")
            AdminAccount.objects.create(username=username, password_hash=hash_password(password))
            self.stdout.write(self.style.SUCCESS(f"Created initial admin account '{username}'."))
        else:
            self.stdout.write("An admin account already exists; credentials were not changed.")

        if not Place.objects.exists():
            Place.objects.bulk_create(Place(**place) for place in SEED_PLACES)
            self.stdout.write(self.style.SUCCESS(f"Added {len(SEED_PLACES)} sample destinations."))
        else:
            self.stdout.write("Destinations already exist; existing records were kept.")

        removed, _ = AdminSession.objects.filter(expires_at__lte=timezone.now()).delete()
        if removed:
            self.stdout.write(f"Removed {removed} expired admin session record(s).")
