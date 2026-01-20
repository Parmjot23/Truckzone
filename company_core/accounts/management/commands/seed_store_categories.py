import re
import time
import urllib.parse
import urllib.request

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction, IntegrityError
from django.db.utils import OperationalError
from django.utils.text import slugify

from accounts.models import Category, CategoryGroup


TRACTION_CATEGORY_URL = "https://www.traction.com/en/categories"

CATEGORY_GROUPS = [
    {
        "name": "AIR BRAKES, DRUMS, ROTORS AND WHEELS",
        "categories": [
            "Air Accessories",
            "Air Management Systems",
            "Drum Brake System",
            "Wheels & Accessories",
        ],
    },
    {
        "name": "OIL, FILTERS AND CHEMICALS",
        "categories": [
            "Chemicals, Antifreeze & Windshield Washer",
            "Filter",
            "Oils",
        ],
    },
    {
        "name": "POWERTRAIN & DRIVELINE SYSTEMS",
        "categories": [
            "Axle & Driveline",
            "Bearings",
            "Belts, Tensioners & Pulleys",
            "Emission System",
            "Engine Parts",
            "Fuel Systems",
            "Seals, O-rings & Gaskets",
            "Transmissions & Clutches",
        ],
    },
    {
        "name": "ELECTRICAL AND BATTERIES",
        "categories": [
            "Batteries",
            "Electrical",
            "Electronics",
            "Starters, Alternators & Motors",
        ],
    },
    {
        "name": "STEERING & SUSPENSION",
        "categories": [
            "Air Springs",
            "Shock Absorbers",
            "Steering",
            "Suspension",
            "Truck Leaf Springs",
        ],
    },
    {
        "name": "VISIBILITY",
        "categories": [
            "Fog & Driving Lights",
            "Lighting",
            "Power Tools",
            "Safety & Signaling",
            "Safety Clothing & Protection Equipments",
            "Signal/Stop/Tail Lights",
            "Warning, Safety & Hazard Lighting",
        ],
    },
    {
        "name": "BODY AND CABIN",
        "categories": [
            "Body Components",
            "Cabin Interior",
            "Chrome & Stainless Steel",
        ],
    },
    {
        "name": "COOLING & HVAC",
        "categories": [
            "Air Conditioning System",
            "Cooling System",
        ],
    },
    {
        "name": "TRAILER & CARGO CONTROL",
        "categories": [
            "Cargo Control, Tarps & Winches",
            "Fifth Wheel, Pintle Hooks",
            "Tanker Parts",
            "Trailer Parts",
            "Utility Trailer Parts",
        ],
    },
    {
        "name": "TOOLS AND FASTENERS",
        "categories": [
            "Equipments",
            "Fasteners & Hardware",
            "Fittings",
            "Hand Tools",
            "Hoses, Pipes & Tubes",
            "Hydraulic Products",
            "Other Applications",
            "Power Tools",
        ],
    },
]


def _normalize_category_key(value):
    value = (value or "").strip().lower()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


_IMAGE_KEY_ALIASES = {
    _normalize_category_key("Safety Clothing & Protection Equipments"): (
        _normalize_category_key("Safety Clothings & Protection Equipments")
    ),
}


def _resolve_image_key(name):
    key = _normalize_category_key(name)
    return _IMAGE_KEY_ALIASES.get(key, key)


def _fetch_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def _fetch_traction_category_tiles(source_url=TRACTION_CATEGORY_URL):
    html = _fetch_html(source_url)
    pattern = re.compile(
        r'<a[^>]+href="([^"]+)"[^>]*>\s*<div[^>]+content-category-box[^>]*>.*?'
        r'<img[^>]+title="([^"]+)"[^>]+src="([^"]+)"',
        re.IGNORECASE | re.DOTALL,
    )
    tiles = {}
    for href, title, src in pattern.findall(html):
        if "TRACTION-WM-400" not in src:
            continue
        title = title.strip()
        if not title:
            continue
        key = _normalize_category_key(title)
        tiles.setdefault(
            key,
            {
                "name": title,
                "url": urllib.parse.urljoin(source_url, href.strip()),
                "image_url": urllib.parse.urljoin(source_url, src.strip()),
            },
        )
    return tiles


def _fetch_traction_subcategories(category_url):
    html = _fetch_html(category_url)
    pattern = re.compile(
        r'<div[^>]+content-subcategory[^>]*>.*?<a href="([^"]+)".*?'
        r'<img title="([^"]+)"[^>]+src="([^"]+)"',
        re.IGNORECASE | re.DOTALL,
    )
    subcategories = []
    seen = set()
    for href, title, src in pattern.findall(html):
        name = title.strip()
        if not name:
            continue
        key = _normalize_category_key(name)
        if key in seen:
            continue
        seen.add(key)
        subcategories.append(
            {
                "name": name,
                "url": urllib.parse.urljoin(category_url, href.strip()),
                "image_url": urllib.parse.urljoin(category_url, src.strip()),
            }
        )
    return subcategories


def _download_image(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "") or ""
    return data, content_type


def _image_extension(content_type):
    content_type = (content_type or "").lower()
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    return ".jpg"


def _apply_category_image(category, image_url, download_cache, force_images=False):
    if category.image and not force_images:
        return "skipped"

    if force_images and category.image:
        category.image.delete(save=False)

    cached = download_cache.get(image_url)
    if cached is None:
        data, content_type = _download_image(image_url)
        download_cache[image_url] = (data, content_type)
    else:
        data, content_type = cached

    extension = _image_extension(content_type)
    filename = f"{slugify(category.name) or 'category'}{extension}"
    category.image.save(filename, ContentFile(data), save=True)
    return "applied"


def _set_sqlite_busy_timeout(milliseconds):
    try:
        if connection.vendor == "sqlite":
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute(f"PRAGMA busy_timeout = {int(milliseconds)}")
    except Exception:
        return


def _is_db_locked_error(exc):
    return "database is locked" in str(exc).lower()


def _run_with_db_retry(func, retries, wait_seconds):
    attempt = 0
    while True:
        try:
            return func()
        except OperationalError as exc:
            if not _is_db_locked_error(exc) or attempt >= retries:
                raise
            connection.close()
            sleep_for = wait_seconds * (2 ** attempt)
            time.sleep(sleep_for)
            attempt += 1


def _truncate_category_name(name, max_length=100):
    value = (name or "").strip()
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip()


def _unique_subcategory_name(base_name, parent_name, existing_categories):
    base_name = _truncate_category_name(base_name)
    base_key = base_name.casefold()
    if base_key not in existing_categories:
        return base_name

    parent_name = (parent_name or "").strip()
    candidates = [
        f"{parent_name} - {base_name}",
        f"{base_name} ({parent_name})",
    ]
    for candidate in candidates:
        candidate = _truncate_category_name(candidate)
        if candidate.casefold() not in existing_categories:
            return candidate

    suffix = 2
    while True:
        candidate = _truncate_category_name(f"{parent_name} - {base_name} {suffix}")
        if candidate.casefold() not in existing_categories:
            return candidate
        suffix += 1


def _seed_subcategories(
    user,
    parent,
    subcategory_map,
    existing_categories,
    download_cache,
    *,
    update_existing=False,
    force_images=False,
    rename_duplicates=True,
):
    counts = {
        "subcategories_created": 0,
        "subcategories_existing": 0,
        "subcategories_updated": 0,
        "subcategories_conflict": 0,
        "subcategories_renamed": 0,
        "images_applied": 0,
        "images_skipped": 0,
        "images_missing": 0,
        "images_failed": 0,
    }
    if not parent or not subcategory_map:
        return counts

    parent_key = _resolve_image_key(parent.name)
    subcategories = subcategory_map.get(parent_key, [])
    if not subcategories:
        return counts

    for sub_order, entry in enumerate(subcategories):
        sub_name = _truncate_category_name(entry.get("name") or "")
        if not sub_name:
            continue
        sub_key = sub_name.casefold()
        existing = existing_categories.get(sub_key)
        if existing:
            if existing.parent_id != parent.id:
                if not rename_duplicates:
                    counts["subcategories_conflict"] += 1
                    continue
                sub_name = _unique_subcategory_name(sub_name, parent.name, existing_categories)
                sub_key = sub_name.casefold()
                if sub_key in existing_categories:
                    counts["subcategories_conflict"] += 1
                    continue
                counts["subcategories_renamed"] += 1
            else:
                counts["subcategories_existing"] += 1
                if update_existing:
                    update_fields = []
                    if existing.group_id != parent.group_id:
                        existing.group = parent.group
                        update_fields.append("group")
                    if existing.sort_order != sub_order:
                        existing.sort_order = sub_order
                        update_fields.append("sort_order")
                    if not existing.is_active:
                        existing.is_active = True
                        update_fields.append("is_active")
                    if update_fields:
                        existing.save(update_fields=update_fields)
                        counts["subcategories_updated"] += 1
                image_url = entry.get("image_url")
                if image_url:
                    try:
                        result = _apply_category_image(
                            existing,
                            image_url,
                            download_cache,
                            force_images=force_images,
                        )
                    except Exception:
                        counts["images_failed"] += 1
                    else:
                        counts[f"images_{result}"] += 1
                else:
                    counts["images_missing"] += 1
                continue

        try:
            subcategory = Category.objects.create(
                user=user,
                name=sub_name,
                group=parent.group,
                parent=parent,
                sort_order=sub_order,
                is_active=True,
            )
        except IntegrityError:
            counts["subcategories_conflict"] += 1
            continue
        existing_categories[sub_key] = subcategory
        counts["subcategories_created"] += 1
        image_url = entry.get("image_url")
        if image_url:
            try:
                result = _apply_category_image(
                    subcategory,
                    image_url,
                    download_cache,
                    force_images=force_images,
                )
            except Exception:
                counts["images_failed"] += 1
            else:
                counts[f"images_{result}"] += 1
        else:
            counts["images_missing"] += 1

    return counts


def _find_template_duplicates():
    seen = {}
    duplicates = []
    for group in CATEGORY_GROUPS:
        group_name = group["name"]
        for category_name in group["categories"]:
            key = category_name.casefold()
            if key in seen:
                duplicates.append((category_name, seen[key], group_name))
            else:
                seen[key] = group_name
    return duplicates


def _seed_for_user(
    user,
    update_existing=False,
    image_map=None,
    download_cache=None,
    force_images=False,
    subcategory_map=None,
    rename_duplicates=True,
):
    if download_cache is None:
        download_cache = {}
    counts = {
        "groups_created": 0,
        "groups_existing": 0,
        "groups_updated": 0,
        "categories_created": 0,
        "categories_existing": 0,
        "categories_updated": 0,
        "categories_conflict": 0,
        "subcategories_created": 0,
        "subcategories_existing": 0,
        "subcategories_updated": 0,
        "subcategories_conflict": 0,
        "subcategories_renamed": 0,
        "images_applied": 0,
        "images_skipped": 0,
        "images_missing": 0,
        "images_failed": 0,
    }

    existing_groups = {
        group.name.casefold(): group
        for group in CategoryGroup.objects.filter(user=user)
    }
    existing_categories = {
        category.name.casefold(): category
        for category in Category.objects.filter(user=user)
    }

    for group_order, entry in enumerate(CATEGORY_GROUPS):
        group_name = entry["name"].strip()
        group_key = group_name.casefold()
        group = existing_groups.get(group_key)

        if group:
            counts["groups_existing"] += 1
            if update_existing:
                update_fields = []
                if group.sort_order != group_order:
                    group.sort_order = group_order
                    update_fields.append("sort_order")
                if not group.is_active:
                    group.is_active = True
                    update_fields.append("is_active")
                if update_fields:
                    group.save(update_fields=update_fields)
                    counts["groups_updated"] += 1
        else:
            group = CategoryGroup.objects.create(
                user=user,
                name=group_name,
                sort_order=group_order,
                is_active=True,
            )
            existing_groups[group_key] = group
            counts["groups_created"] += 1

        for category_order, category_name in enumerate(entry["categories"]):
            category_name = category_name.strip()
            category_key = category_name.casefold()
            category = existing_categories.get(category_key)

            if category:
                counts["categories_existing"] += 1
                if update_existing:
                    update_fields = []
                    if category.group_id != group.id:
                        category.group = group
                        update_fields.append("group")
                    if category.sort_order != category_order:
                        category.sort_order = category_order
                        update_fields.append("sort_order")
                    if not category.is_active:
                        category.is_active = True
                        update_fields.append("is_active")
                    if update_fields:
                        category.save(update_fields=update_fields)
                        counts["categories_updated"] += 1
                elif category.group_id and category.group_id != group.id:
                    counts["categories_conflict"] += 1
                if image_map:
                    status = _maybe_apply_image(
                        category,
                        category_name,
                        image_map,
                        download_cache,
                        force_images,
                    )
                    counts[f"images_{status}"] += 1
                if subcategory_map:
                    sub_counts = _seed_subcategories(
                        user,
                        category,
                        subcategory_map,
                        existing_categories,
                        download_cache,
                        update_existing=update_existing,
                        force_images=force_images,
                        rename_duplicates=rename_duplicates,
                    )
                    for key, value in sub_counts.items():
                        counts[key] += value
                continue

            category = Category.objects.create(
                user=user,
                name=category_name,
                group=group,
                sort_order=category_order,
                is_active=True,
            )
            existing_categories[category_key] = category
            counts["categories_created"] += 1
            if image_map:
                status = _maybe_apply_image(
                    category,
                    category_name,
                    image_map,
                    download_cache,
                    force_images,
                )
                counts[f"images_{status}"] += 1
            if subcategory_map:
                sub_counts = _seed_subcategories(
                    user,
                    category,
                    subcategory_map,
                    existing_categories,
                    download_cache,
                    update_existing=update_existing,
                    force_images=force_images,
                    rename_duplicates=rename_duplicates,
                )
                for key, value in sub_counts.items():
                    counts[key] += value

    return counts


def _maybe_apply_image(category, category_name, image_map, download_cache, force_images):
    key = _resolve_image_key(category_name)
    image_url = image_map.get(key)
    if not image_url:
        return "missing"
    try:
        result = _apply_category_image(
            category,
            image_url,
            download_cache,
            force_images=force_images,
        )
    except Exception:
        return "failed"
    return result if result else "failed"


class Command(BaseCommand):
    help = "Seed storefront category groups, categories, and subcategories for one user or all users."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument(
            "--username",
            help="Username to seed categories for.",
        )
        scope.add_argument(
            "--all-users",
            action="store_true",
            help="Seed categories for all users.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive users when using --all-users.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update group assignments, sort order, and activation state for existing categories/groups.",
        )
        parser.add_argument(
            "--with-images",
            action="store_true",
            help="Fetch and attach category images from traction.com.",
        )
        parser.add_argument(
            "--with-subcategories",
            action="store_true",
            help="Create subcategories from traction.com (includes subcategory images).",
        )
        parser.add_argument(
            "--no-atomic",
            action="store_true",
            help="Skip wrapping each user in a single transaction (useful for SQLite).",
        )
        parser.add_argument(
            "--db-lock-retries",
            type=int,
            default=5,
            help="Retry count when SQLite reports 'database is locked'.",
        )
        parser.add_argument(
            "--db-lock-wait",
            type=float,
            default=1.5,
            help="Base wait seconds between SQLite lock retries (exponential backoff).",
        )
        parser.add_argument(
            "--no-rename-duplicates",
            action="store_true",
            help="Skip subcategories that conflict with existing names instead of renaming.",
        )
        parser.add_argument(
            "--force-images",
            action="store_true",
            help="Replace existing category images when using image scraping options.",
        )
        parser.add_argument(
            "--image-source-url",
            default=TRACTION_CATEGORY_URL,
            help="Source URL to scrape category images from.",
        )

    def handle(self, *args, **options):
        username = (options.get("username") or "").strip()
        update_existing = options.get("update_existing", False)
        include_inactive = options.get("include_inactive", False)
        apply_all = options.get("all_users", False)
        with_images = options.get("with_images", False)
        with_subcategories = options.get("with_subcategories", False)
        use_atomic = not options.get("no_atomic", False)
        db_lock_retries = max(int(options.get("db_lock_retries", 5)), 0)
        db_lock_wait = float(options.get("db_lock_wait", 1.5))
        rename_duplicates = not options.get("no_rename_duplicates", False)
        force_images = options.get("force_images", False)
        image_source_url = (options.get("image_source_url") or "").strip() or TRACTION_CATEGORY_URL

        User = get_user_model()

        if apply_all:
            users = User.objects.all()
            if not include_inactive:
                users = users.filter(is_active=True)
            users = list(users.order_by("username"))
        else:
            if not username:
                raise CommandError("--username is required when --all-users is not set.")
            user = User.objects.filter(username__iexact=username).first()
            if not user:
                raise CommandError(f"User not found: {username}")
            users = [user]

        duplicates = _find_template_duplicates()
        for name, first_group, second_group in duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"Duplicate category name '{name}' appears in both "
                    f"'{first_group}' and '{second_group}'. Only one can exist per user."
                )
            )

        if not users:
            raise CommandError("No users matched the provided selection.")

        if force_images and not (with_images or with_subcategories):
            self.stdout.write(
                self.style.WARNING("--force-images has no effect without image scraping.")
            )

        _set_sqlite_busy_timeout(int(max(30000, db_lock_wait * 1000 * max(db_lock_retries, 1))))

        category_tiles = None
        image_map = None
        subcategory_map = None
        download_cache = {}
        if with_images or with_subcategories:
            try:
                category_tiles = _fetch_traction_category_tiles(image_source_url)
            except Exception as exc:
                raise CommandError(f"Unable to fetch category tiles: {exc}") from exc
            if not category_tiles:
                raise CommandError("No category tiles found at the source URL.")
            if with_images:
                image_map = {
                    key: tile["image_url"] for key, tile in category_tiles.items()
                }
            if with_subcategories:
                subcategory_map = {}
                missing_categories = []
                for entry in CATEGORY_GROUPS:
                    for category_name in entry["categories"]:
                        parent_key = _resolve_image_key(category_name)
                        tile = category_tiles.get(parent_key)
                        if not tile:
                            missing_categories.append(category_name)
                            continue
                        try:
                            subcategories = _fetch_traction_subcategories(tile["url"])
                        except Exception:
                            missing_categories.append(category_name)
                            continue
                        if subcategories:
                            subcategory_map[parent_key] = subcategories
                if missing_categories:
                    sample = ", ".join(missing_categories[:8])
                    self.stdout.write(
                        self.style.WARNING(
                            "Subcategories not found for: "
                            f"{sample}{'...' if len(missing_categories) > 8 else ''}"
                        )
                    )

        for user in users:
            def _execute_seed():
                if use_atomic:
                    with transaction.atomic():
                        return _seed_for_user(
                            user,
                            update_existing=update_existing,
                            image_map=image_map,
                            download_cache=download_cache,
                            force_images=force_images,
                            subcategory_map=subcategory_map,
                            rename_duplicates=rename_duplicates,
                        )
                return _seed_for_user(
                    user,
                    update_existing=update_existing,
                    image_map=image_map,
                    download_cache=download_cache,
                    force_images=force_images,
                    subcategory_map=subcategory_map,
                    rename_duplicates=rename_duplicates,
                )

            counts = _run_with_db_retry(_execute_seed, db_lock_retries, db_lock_wait)

            self.stdout.write(
                self.style.SUCCESS(
                    "Seeded categories for "
                    f"{user.username}: "
                    f"groups created={counts['groups_created']}, "
                    f"groups updated={counts['groups_updated']}, "
                    f"categories created={counts['categories_created']}, "
                    f"categories updated={counts['categories_updated']}, "
                    f"category conflicts={counts['categories_conflict']}, "
                    f"subcategories created={counts['subcategories_created']}, "
                    f"subcategories existing={counts['subcategories_existing']}, "
                    f"subcategories updated={counts['subcategories_updated']}, "
                    f"subcategory conflicts={counts['subcategories_conflict']}, "
                    f"subcategories renamed={counts['subcategories_renamed']}, "
                    f"images applied={counts['images_applied']}, "
                    f"images skipped={counts['images_skipped']}, "
                    f"images missing={counts['images_missing']}, "
                    f"images failed={counts['images_failed']}."
                )
            )
