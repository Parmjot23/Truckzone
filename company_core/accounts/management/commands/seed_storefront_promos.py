from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from itertools import cycle

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import (
    Profile,
    Product,
    StorefrontFlyer,
    StorefrontHeroPackage,
    StorefrontHeroShowcase,
    StorefrontHeroShowcaseItem,
    StorefrontMessageBanner,
)
from accounts.utils import get_product_user_ids


DISCOUNT_SEQUENCE = [10, 12, 15, 18, 20, 25]
PACKAGE_TEMPLATES = [
    {
        "title": "Brake & Rotor Bundle",
        "subtitle": "Pads, rotors, and hardware staged for heavy-duty stops.",
        "discount": 12,
    },
    {
        "title": "Lighting Safety Pack",
        "subtitle": "LED markers, reflectors, and wiring for night runs.",
        "discount": 10,
    },
    {
        "title": "Winter Road Kit",
        "subtitle": "De-icer, chains, and emergency accessories for snow season.",
        "discount": 15,
    },
    {
        "title": "Air & Fuel Service Combo",
        "subtitle": "Filters, hoses, and fittings for scheduled service checks.",
        "discount": 8,
    },
]
FLYER_TITLES = [
    "Weekly Deals & Fleet Bundles",
    "Fleet Parts Weekly Flyer",
    "Promo Spotlight & Package Savings",
]
FLYER_SUBTITLES = [
    "Featured discounts across brakes, lighting, and filters.",
    "Bundle savings for fleet-ready orders.",
    "Fresh promos updated every week for your shop.",
]
BANNER_MESSAGES = [
    "Weekly promos are live: fleet-ready bundles and bulk savings.",
    "Save on service essentials with limited-time package deals.",
    "Stock up on shop favorites with rotating promo specials.",
]


def _calculate_discounted_price(sale_price, discount_percent):
    if sale_price is None or discount_percent is None:
        return None
    if sale_price <= Decimal("0.00"):
        return None
    percent = Decimal(discount_percent) / Decimal("100")
    discounted = sale_price * (Decimal("1.00") - percent)
    return discounted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ensure_promotion_price(product, discount_percent):
    sale_price = product.sale_price
    if sale_price is None:
        return discount_percent
    promo = product.promotion_price
    if promo is not None and promo < sale_price:
        return product.promotion_discount_percent
    discounted = _calculate_discounted_price(sale_price, discount_percent)
    if discounted is None:
        return product.promotion_discount_percent
    if promo is None or discounted < promo:
        product.promotion_price = discounted
        product.save(update_fields=["promotion_price", "updated_at"])
    return product.promotion_discount_percent or discount_percent


def _select_products(preferred_qs, fallback_qs, count, exclude_ids=None):
    exclude_ids = set(exclude_ids or [])
    selected = []

    def extend_from(qs):
        nonlocal selected
        if len(selected) >= count:
            return
        used_ids = exclude_ids.union({product.id for product in selected})
        needed = count - len(selected)
        selected.extend(list(qs.exclude(id__in=used_ids)[:needed]))

    extend_from(preferred_qs.filter(image__isnull=False, sale_price__isnull=False).order_by("-updated_at"))
    extend_from(preferred_qs.filter(sale_price__isnull=False).order_by("-updated_at"))
    extend_from(preferred_qs.order_by("-updated_at"))
    extend_from(fallback_qs.filter(image__isnull=False, sale_price__isnull=False).order_by("-updated_at"))
    extend_from(fallback_qs.filter(sale_price__isnull=False).order_by("-updated_at"))
    extend_from(fallback_qs.order_by("-updated_at"))
    return selected


class Command(BaseCommand):
    help = "Seed storefront promo slides, packages, and flyers for store accounts."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Seed promos for a single store username.")
        parser.add_argument(
            "--slides",
            type=int,
            default=4,
            help="Target number of promo slides per store.",
        )
        parser.add_argument(
            "--packages",
            type=int,
            default=2,
            help="Target number of package deals per store.",
        )
        parser.add_argument(
            "--force-text",
            action="store_true",
            help="Overwrite existing flyer/banner text.",
        )

    def handle(self, *args, **options):
        username = (options.get("username") or "").strip()
        slides_target = max(int(options.get("slides") or 0), 0)
        packages_target = max(int(options.get("packages") or 0), 0)
        force_text = bool(options.get("force_text"))

        store_users = self._resolve_store_users(username)
        if not store_users:
            raise CommandError("No store accounts found to seed.")

        totals = {
            "stores": 0,
            "slides_created": 0,
            "packages_created": 0,
            "products_published": 0,
            "promos_set": 0,
            "flyers_updated": 0,
            "banners_updated": 0,
        }
        for index, store_user in enumerate(store_users):
            with transaction.atomic():
                summary = self._seed_for_store(
                    store_user,
                    index=index,
                    slides_target=slides_target,
                    packages_target=packages_target,
                    force_text=force_text,
                )
            totals["stores"] += 1
            for key, value in summary.items():
                totals[key] += value

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded storefront promos for "
                f"{totals['stores']} store(s): "
                f"{totals['slides_created']} slide(s), "
                f"{totals['packages_created']} package(s), "
                f"{totals['products_published']} product(s) published, "
                f"{totals['promos_set']} promo price(s) set."
            )
        )
        if totals["flyers_updated"] or totals["banners_updated"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {totals['flyers_updated']} flyer(s) "
                    f"and {totals['banners_updated']} banner(s)."
                )
            )

    def _resolve_store_users(self, username):
        UserModel = get_user_model()
        if username:
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist as exc:
                raise CommandError(f"User not found: {username}") from exc
            return [user]

        profiles = (
            Profile.objects.select_related("user")
            .filter(occupation="parts_store", user__is_active=True)
            .order_by("user__username")
        )
        return [profile.user for profile in profiles]

    def _seed_for_store(self, store_user, *, index, slides_target, packages_target, force_text):
        hero, _ = StorefrontHeroShowcase.objects.get_or_create(user=store_user)
        banner, _ = StorefrontMessageBanner.objects.get_or_create(user=store_user)
        flyer, _ = StorefrontFlyer.objects.get_or_create(user=store_user)

        flyer_title = FLYER_TITLES[index % len(FLYER_TITLES)]
        flyer_subtitle = FLYER_SUBTITLES[index % len(FLYER_SUBTITLES)]
        flyer_dirty = False
        if not flyer.is_active:
            flyer.is_active = True
            flyer_dirty = True
        if force_text or not (flyer.title or "").strip():
            flyer.title = flyer_title
            flyer_dirty = True
        if force_text or not (flyer.subtitle or "").strip():
            flyer.subtitle = flyer_subtitle
            flyer_dirty = True
        if flyer_dirty:
            flyer.save()

        banner_message = BANNER_MESSAGES[index % len(BANNER_MESSAGES)]
        banner_dirty = False
        if not banner.is_active:
            banner.is_active = True
            banner_dirty = True
        if force_text or not (banner.message or "").strip():
            banner.message = banner_message
            banner_dirty = True
        if force_text or not (banner.link_text or "").strip():
            banner.link_text = "View deals"
            banner_dirty = True
        if force_text or not (banner.link_url or "").strip():
            banner.link_url = "/store/"
            banner_dirty = True
        if force_text or not (banner.theme or "").strip():
            banner.theme = hero.gradient_theme or "sky"
            banner_dirty = True
        if banner_dirty:
            banner.save()

        user_ids = get_product_user_ids(store_user) or [store_user.id]
        base_qs = Product.objects.filter(user__in=user_ids)
        published_qs = base_qs.filter(is_published_to_store=True)

        summary = {
            "slides_created": 0,
            "packages_created": 0,
            "products_published": 0,
            "promos_set": 0,
            "flyers_updated": 1 if flyer_dirty else 0,
            "banners_updated": 1 if banner_dirty else 0,
        }

        existing_slide_ids = set(
            StorefrontHeroShowcaseItem.objects.filter(hero=hero)
            .values_list("product_id", flat=True)
        )
        slides_needed = max(slides_target - len(existing_slide_ids), 0)
        if slides_needed > 0:
            slide_products = _select_products(
                published_qs,
                base_qs,
                slides_needed,
                exclude_ids=existing_slide_ids,
            )
            discount_cycle = cycle(DISCOUNT_SEQUENCE)
            for product in slide_products:
                discount_value = _ensure_promotion_price(product, next(discount_cycle))
                if product.promotion_price is not None:
                    summary["promos_set"] += 1
                if not product.is_published_to_store:
                    product.is_published_to_store = True
                    product.save(update_fields=["is_published_to_store", "updated_at"])
                    summary["products_published"] += 1
                StorefrontHeroShowcaseItem.objects.create(
                    hero=hero,
                    product=product,
                    discount_percent=discount_value,
                )
                summary["slides_created"] += 1

        existing_package_count = StorefrontHeroPackage.objects.filter(user=store_user).count()
        packages_needed = max(packages_target - existing_package_count, 0)
        if packages_needed > 0:
            package_products = _select_products(
                published_qs,
                base_qs,
                packages_needed * 3,
                exclude_ids=existing_slide_ids,
            )
            if not package_products:
                package_products = _select_products(published_qs, base_qs, packages_needed * 3)
            if not package_products:
                return summary
            product_cursor = 0
            existing_titles = set(
                StorefrontHeroPackage.objects.filter(user=store_user)
                .values_list("title", flat=True)
            )
            for package_index in range(packages_needed):
                template = PACKAGE_TEMPLATES[package_index % len(PACKAGE_TEMPLATES)]
                title = template["title"]
                if title in existing_titles:
                    title = f"{title} {package_index + 1}"
                existing_titles.add(title)

                primary = package_products[product_cursor % len(package_products)]
                product_cursor += 1
                secondary = None
                free = None
                if len(package_products) > 1:
                    secondary = package_products[product_cursor % len(package_products)]
                    product_cursor += 1
                if len(package_products) > 2:
                    free = package_products[product_cursor % len(package_products)]
                    product_cursor += 1

                for product in (primary, secondary, free):
                    if product and not product.is_published_to_store:
                        product.is_published_to_store = True
                        product.save(update_fields=["is_published_to_store", "updated_at"])
                        summary["products_published"] += 1

                discount_percent = template["discount"]
                for product in (primary, secondary):
                    if product:
                        _ensure_promotion_price(product, discount_percent)
                        if product.promotion_price is not None:
                            summary["promos_set"] += 1

                StorefrontHeroPackage.objects.create(
                    user=store_user,
                    title=title,
                    subtitle=template["subtitle"],
                    primary_product=primary,
                    secondary_product=secondary,
                    free_product=free,
                    discount_percent=discount_percent,
                    is_active=True,
                )
                summary["packages_created"] += 1

        return summary
