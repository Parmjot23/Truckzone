import json
import random
import re
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from html import unescape

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, IntegrityError, transaction
from django.db.utils import OperationalError
from django.utils.text import slugify

from accounts.models import (
    Category,
    CategoryAttribute,
    CategoryAttributeOption,
    Product,
    ProductAlternateSku,
    ProductAttributeValue,
    ProductBrand,
)
from .seed_store_categories import (
    TRACTION_CATEGORY_URL,
    _fetch_traction_category_tiles,
    _fetch_traction_subcategories,
    _normalize_category_key,
    _resolve_image_key,
)


TRACTION_SEARCH_URL = "https://www.traction.com/en/search/"
TRACTION_SOURCE_NAME = "Traction"


def _fetch_html(url, referer=None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


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


def _clean_text(value):
    if value is None:
        return ""
    value = unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _truncate_text(value, max_length):
    value = (value or "").strip()
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip()


def _extract_category_code(url):
    if not url:
        return None
    match = re.search(r"/c/([a-zA-Z0-9_]+)", url)
    return match.group(1) if match else None


def _build_search_url(category_code, page=0):
    query = f":relevance:category:{category_code}"
    params = {
        "q": query,
        "view": "GRID",
        "page": str(page),
    }
    return f"{TRACTION_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def _split_product_items(html):
    marker = '<div class="product-item'
    if marker not in html:
        return []
    parts = html.split(marker)
    return [marker + part for part in parts[1:]]


def _parse_product_item(chunk):
    name = None
    url = None
    sku = None
    image_url = None
    brand = None

    name_match = re.search(
        r'class="product__list--name[^"]*"[^>]*>(.*?)</a>',
        chunk,
        re.DOTALL | re.IGNORECASE,
    )
    if name_match:
        name = _clean_text(name_match.group(1))

    url_match = re.search(
        r'class="product__list--name[^"]*"[^>]*href="([^"]+)"',
        chunk,
        re.IGNORECASE,
    )
    if url_match:
        url = urllib.parse.urljoin(TRACTION_SEARCH_URL, url_match.group(1).strip())

    sku_match = re.search(
        r'class="productcode"[^>]*>\s*#?\s*([^<\s]+)',
        chunk,
        re.IGNORECASE,
    )
    if sku_match:
        sku = sku_match.group(1).strip()
    else:
        sku_match = re.search(r'data-productid="([^"]+)"', chunk, re.IGNORECASE)
        if sku_match:
            sku = sku_match.group(1).strip()

    image_match = re.search(
        r'class="product__list--thumb[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
        chunk,
        re.DOTALL | re.IGNORECASE,
    )
    if image_match:
        image_url = image_match.group(1).strip()

    brand_match = re.search(
        r'class="productfeatures[^"]*"[^>]*>(.*?)</a>',
        chunk,
        re.DOTALL | re.IGNORECASE,
    )
    if brand_match:
        brand = _clean_text(brand_match.group(1))

    return {
        "name": name,
        "url": url,
        "sku": sku,
        "image_url": image_url,
        "brand": brand,
    }


def _parse_price(text):
    if not text:
        return None
    match = re.search(r"\$?\s*([0-9]+(?:\.[0-9]{1,2})?)", text.replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except Exception:
        return None


def _parse_product_json_ld(html):
    for match in re.finditer(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = match.group(1).strip()
        if '"@type"' not in raw or "Product" not in raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if payload.get("@type") == "Product":
            return payload
    return {}


def _parse_product_details(html):
    specs = {}
    interchange = []
    description = ""
    price = None
    image_url = None

    meta_description = re.search(
        r'property="og:description"[^>]*content="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    if meta_description:
        description = _clean_text(meta_description.group(1))

    price_match = re.search(
        r'class="price-value"[^>]*>(.*?)</',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if price_match:
        price = _parse_price(_clean_text(price_match.group(1)))

    sell_price_match = re.search(
        r'"sellPrice"\s*:\s*"([^"]+)"',
        html,
        re.IGNORECASE,
    )
    if price is None and sell_price_match:
        price = _parse_price(sell_price_match.group(1))

    json_ld = _parse_product_json_ld(html)
    if not description:
        description = _clean_text(json_ld.get("description", ""))
    if json_ld.get("image"):
        images = json_ld.get("image")
        if isinstance(images, list) and images:
            image_url = images[0]
        elif isinstance(images, str):
            image_url = images

    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_match.group(1), re.DOTALL | re.IGNORECASE)
        if len(tds) >= 2:
            name = _clean_text(tds[0])
            value = _clean_text(tds[1])
            if name and value:
                specs[name] = value

    for table_match in re.finditer(
        r'<table[^>]+class="[^"]*interchange[^"]*"[^>]*>(.*?)</table>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        for td_match in re.finditer(r"<td[^>]*>(.*?)</td>", table_match.group(1), re.DOTALL | re.IGNORECASE):
            value = _clean_text(td_match.group(1))
            if value:
                interchange.append(value)

    return {
        "description": description,
        "price": price,
        "image_url": image_url,
        "specs": specs,
        "interchange": interchange,
    }


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


def _build_category_maps(source_url):
    tiles = _fetch_traction_category_tiles(source_url)
    category_code_map = {}
    subcategory_map = {}

    for key, entry in tiles.items():
        code = _extract_category_code(entry.get("url"))
        if code:
            category_code_map[key] = {
                "code": code,
                "url": entry.get("url"),
            }
        subcategory_map[key] = _fetch_traction_subcategories(entry.get("url"))

    return category_code_map, subcategory_map


def _match_subcategory_entry(subcategory_name, parent_name, subcategories):
    if not subcategory_name or not subcategories:
        return None
    normalized = _normalize_category_key(subcategory_name)
    sub_lookup = {_normalize_category_key(entry["name"]): entry for entry in subcategories}
    if normalized in sub_lookup:
        return sub_lookup[normalized]

    parent_norm = _normalize_category_key(parent_name)
    candidate = subcategory_name
    if normalized.startswith(parent_norm):
        candidate = subcategory_name[len(parent_name):].lstrip(" -:/")
    elif normalized.endswith(parent_norm):
        candidate = subcategory_name[: -len(parent_name)].rstrip(" -:/")
    candidate_norm = _normalize_category_key(candidate)
    if candidate_norm in sub_lookup:
        return sub_lookup[candidate_norm]

    for key, entry in sub_lookup.items():
        if key and key in normalized:
            return entry
    return None


def _resolve_category_code(category, category_code_map, subcategory_map):
    if category.parent_id:
        parent_key = _resolve_image_key(category.parent.name)
        entries = subcategory_map.get(parent_key, [])
        match = _match_subcategory_entry(category.name, category.parent.name, entries)
        if not match:
            return None
        return _extract_category_code(match.get("url"))

    key = _resolve_image_key(category.name)
    entry = category_code_map.get(key)
    if entry:
        return entry["code"]

    normalized = _normalize_category_key(category.name)
    for mapped_key, mapped_entry in category_code_map.items():
        if normalized in mapped_key or mapped_key in normalized:
            return mapped_entry["code"]
    return None


def _get_or_create_brand(user, brand_name):
    if not brand_name:
        return None
    normalized = brand_name.strip()
    if not normalized:
        return None
    brand = ProductBrand.objects.filter(user=user, name__iexact=normalized).first()
    if brand:
        return brand
    return ProductBrand.objects.create(user=user, name=normalized, is_active=True)


def _ensure_attribute(user, category, name, cache):
    normalized = _normalize_category_key(name)
    cache_key = (category.id, normalized)
    if cache_key in cache:
        return cache[cache_key], False
    attribute = CategoryAttribute.objects.filter(
        user=user,
        category=category,
        name__iexact=name,
    ).first()
    if not attribute:
        attribute = CategoryAttribute.objects.create(
            user=user,
            category=category,
            name=_truncate_text(name, 120),
            attribute_type="select",
            is_filterable=True,
            is_active=True,
        )
        created = True
    else:
        created = False
    cache[cache_key] = attribute
    return attribute, created


def _ensure_attribute_option(attribute, value, cache):
    normalized = _normalize_category_key(value)
    cache_key = (attribute.id, normalized)
    if cache_key in cache:
        return cache[cache_key], False
    option = CategoryAttributeOption.objects.filter(
        attribute=attribute,
        value__iexact=value,
    ).first()
    if not option:
        option = CategoryAttributeOption.objects.create(
            attribute=attribute,
            value=_truncate_text(value, 120),
        )
        created = True
    else:
        created = False
    cache[cache_key] = option
    return option, created


def _set_product_attributes(product, specs, attribute_cache, option_cache):
    counts = {"attributes_created": 0, "attribute_values_set": 0}
    if not specs:
        return counts

    for name, value in specs.items():
        if not name or not value:
            continue
        attribute, attribute_created = _ensure_attribute(
            product.user,
            product.category,
            name,
            attribute_cache,
        )
        if attribute_created:
            counts["attributes_created"] += 1
        option, option_created = _ensure_attribute_option(attribute, value, option_cache)
        if option_created:
            counts["attributes_created"] += 1
        ProductAttributeValue.objects.update_or_create(
            product=product,
            attribute=attribute,
            defaults={
                "option": option,
                "value_text": "",
                "value_number": None,
                "value_boolean": None,
            },
        )
        counts["attribute_values_set"] += 1

    return counts


def _apply_product_image(product, image_url, download_cache, force_images=False):
    if product.image and not force_images:
        return "skipped"

    if force_images and product.image:
        product.image.delete(save=False)

    cached = download_cache.get(image_url)
    if cached is None:
        data, content_type = _download_image(image_url)
        download_cache[image_url] = (data, content_type)
    else:
        data, content_type = cached

    extension = _image_extension(content_type)
    filename = f"{slugify(product.name) or 'product'}{extension}"
    product.image.save(filename, ContentFile(data), save=True)
    return "applied"


def _build_fallback_sku(name, user):
    base = slugify(name)[:60] or "product"
    candidate = base.upper()
    counter = 1
    while Product.objects.filter(user=user, sku__iexact=candidate).exists():
        candidate = f"{base}-{counter}".upper()
        counter += 1
    return candidate


def _seed_for_user(
    user,
    category_code_map,
    subcategory_map,
    *,
    max_per_category=50,
    with_images=False,
    force_images=False,
    request_delay=0.0,
    update_existing=False,
):
    counts = {
        "categories_processed": 0,
        "categories_skipped": 0,
        "products_created": 0,
        "products_existing": 0,
        "products_updated": 0,
        "products_skipped": 0,
        "images_applied": 0,
        "images_skipped": 0,
        "images_failed": 0,
        "attributes_created": 0,
        "attribute_values_set": 0,
        "alternate_skus_created": 0,
        "alternate_skus_existing": 0,
    }

    categories = list(Category.objects.filter(user=user).select_related("parent").order_by("id"))
    subcategories = [cat for cat in categories if cat.parent_id]
    root_categories = [cat for cat in categories if not cat.parent_id]

    attribute_cache = {}
    option_cache = {}
    download_cache = {}

    def process_category(category):
        category_code = _resolve_category_code(category, category_code_map, subcategory_map)
        if not category_code:
            counts["categories_skipped"] += 1
            return

        counts["categories_processed"] += 1
        seen_products = set()
        collected = []
        page = 0
        max_pages = max(1, (max_per_category // 20) + 3)

        while len(collected) < max_per_category and page < max_pages:
            search_url = _build_search_url(category_code, page=page)
            html = _fetch_html(search_url, referer=TRACTION_CATEGORY_URL)
            items = []
            for chunk in _split_product_items(html):
                item = _parse_product_item(chunk)
                if not item.get("name"):
                    continue
                key = (item.get("sku") or item.get("url") or item.get("name") or "").casefold()
                if not key or key in seen_products:
                    continue
                seen_products.add(key)
                items.append(item)
                if len(collected) + len(items) >= max_per_category:
                    break
            if not items:
                break
            collected.extend(items)
            page += 1
            if request_delay:
                time.sleep(request_delay)

        for item in collected[:max_per_category]:
            sku = _truncate_text(item.get("sku") or "", 100)
            name = _truncate_text(item.get("name") or "", 150)
            if not name:
                counts["products_skipped"] += 1
                continue
            if not sku:
                sku = _build_fallback_sku(name, user)

            details = {}
            if item.get("url"):
                details_html = _fetch_html(item["url"], referer=TRACTION_SEARCH_URL)
                details = _parse_product_details(details_html)
                if request_delay:
                    time.sleep(request_delay)

            product = Product.objects.filter(user=user, sku__iexact=sku).first()
            if not product:
                brand = _get_or_create_brand(user, item.get("brand"))
                price = details.get("price")
                if price is None or price <= 0:
                    price = Decimal(random.randint(1, 50))

                product = Product.objects.create(
                    user=user,
                    sku=sku,
                    name=name,
                    description=_truncate_text(details.get("description", ""), 2000) or None,
                    item_type="inventory",
                    category=category,
                    brand=brand,
                    source_name=TRACTION_SOURCE_NAME,
                    source_url=item.get("url"),
                    source_product_id=sku,
                    cost_price=price,
                    sale_price=price,
                    quantity_in_stock=0,
                    is_published_to_store=True,
                )
                counts["products_created"] += 1
            else:
                counts["products_existing"] += 1

            update_fields = []
            if update_existing and product.category_id != category.id:
                product.category = category
                update_fields.append("category")
            if update_existing and not product.source_url and item.get("url"):
                product.source_url = item.get("url")
                update_fields.append("source_url")
            if update_existing and not product.source_name:
                product.source_name = TRACTION_SOURCE_NAME
                update_fields.append("source_name")
            if update_existing and not product.source_product_id and sku:
                product.source_product_id = sku
                update_fields.append("source_product_id")
            if update_existing and not product.description:
                description = _truncate_text(details.get("description", ""), 2000)
                if description:
                    product.description = description
                    update_fields.append("description")
            if update_fields:
                product.save(update_fields=update_fields)
                counts["products_updated"] += 1

            if details.get("specs") and product.category_id:
                attr_counts = _set_product_attributes(
                    product,
                    details["specs"],
                    attribute_cache,
                    option_cache,
                )
                counts["attributes_created"] += attr_counts["attributes_created"]
                counts["attribute_values_set"] += attr_counts["attribute_values_set"]

            for alt in details.get("interchange", []):
                alt_sku = _truncate_text(alt, 100)
                if not alt_sku or alt_sku.casefold() == sku.casefold():
                    continue
                existing_alt = ProductAlternateSku.objects.filter(
                    product=product,
                    sku__iexact=alt_sku,
                ).first()
                if existing_alt:
                    counts["alternate_skus_existing"] += 1
                    continue
                try:
                    ProductAlternateSku.objects.create(
                        product=product,
                        sku=alt_sku,
                        kind="interchange",
                        source_name=TRACTION_SOURCE_NAME,
                    )
                except IntegrityError:
                    counts["alternate_skus_existing"] += 1
                else:
                    counts["alternate_skus_created"] += 1

            if with_images:
                image_url = item.get("image_url") or details.get("image_url")
                if image_url:
                    try:
                        result = _apply_product_image(
                            product,
                            image_url,
                            download_cache,
                            force_images=force_images,
                        )
                    except Exception:
                        counts["images_failed"] += 1
                    else:
                        counts[f"images_{result}"] += 1

    for category in subcategories + root_categories:
        process_category(category)

    return counts


class Command(BaseCommand):
    help = "Seed products for storefront categories from traction.com."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--username", help="Username to seed products for.")
        scope.add_argument("--all-users", action="store_true", help="Seed products for all users.")
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive users when using --all-users.",
        )
        parser.add_argument(
            "--max-per-category",
            type=int,
            default=50,
            help="Maximum number of products to seed per category or subcategory.",
        )
        parser.add_argument(
            "--with-images",
            action="store_true",
            help="Download and attach product images.",
        )
        parser.add_argument(
            "--force-images",
            action="store_true",
            help="Replace existing product images when using --with-images.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update existing products with missing source fields or categories.",
        )
        parser.add_argument(
            "--request-delay",
            type=float,
            default=0.2,
            help="Seconds to wait between external requests.",
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
            "--category-source-url",
            default=TRACTION_CATEGORY_URL,
            help="Source URL to scrape category mappings from.",
        )

    def handle(self, *args, **options):
        username = (options.get("username") or "").strip()
        include_inactive = options.get("include_inactive", False)
        apply_all = options.get("all_users", False)
        max_per_category = max(int(options.get("max_per_category", 50)), 1)
        with_images = options.get("with_images", False)
        force_images = options.get("force_images", False)
        update_existing = options.get("update_existing", False)
        request_delay = max(float(options.get("request_delay", 0.0)), 0.0)
        use_atomic = not options.get("no_atomic", False)
        db_lock_retries = max(int(options.get("db_lock_retries", 5)), 0)
        db_lock_wait = float(options.get("db_lock_wait", 1.5))
        category_source_url = (options.get("category_source_url") or "").strip() or TRACTION_CATEGORY_URL

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

        if not users:
            raise CommandError("No users matched the provided selection.")

        if force_images and not with_images:
            self.stdout.write(
                self.style.WARNING("--force-images has no effect without --with-images.")
            )

        _set_sqlite_busy_timeout(int(max(30000, db_lock_wait * 1000 * max(db_lock_retries, 1))))

        category_code_map, subcategory_map = _build_category_maps(category_source_url)

        for user in users:
            def run_seed():
                return _seed_for_user(
                    user,
                    category_code_map,
                    subcategory_map,
                    max_per_category=max_per_category,
                    with_images=with_images,
                    force_images=force_images,
                    request_delay=request_delay,
                    update_existing=update_existing,
                )

            if use_atomic:
                def atomic_call():
                    with transaction.atomic():
                        return run_seed()
                counts = _run_with_db_retry(atomic_call, db_lock_retries, db_lock_wait)
            else:
                counts = _run_with_db_retry(run_seed, db_lock_retries, db_lock_wait)

            self.stdout.write(
                self.style.SUCCESS(
                    f"{user.username}: "
                    f"categories={counts['categories_processed']} "
                    f"skipped={counts['categories_skipped']} "
                    f"created={counts['products_created']} "
                    f"existing={counts['products_existing']} "
                    f"updated={counts['products_updated']} "
                    f"attributes={counts['attribute_values_set']} "
                    f"alt_skus={counts['alternate_skus_created']} "
                    f"images_applied={counts['images_applied']} "
                    f"images_skipped={counts['images_skipped']} "
                    f"images_failed={counts['images_failed']}"
                )
            )
