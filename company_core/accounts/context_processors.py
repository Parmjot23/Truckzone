from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum

from django.conf import settings
from django.templatetags.static import static

from .models import Category, Product, ProductBrand, Profile, StorefrontCartItem
from .utils import (
    get_default_store_owner,
    get_product_user_ids,
    get_storefront_owner,
    get_storefront_profiles,
    resolve_storefront_root_user,
    resolve_storefront_category_flags,
)

_FONT_FAMILY_STACKS = {
    'manrope': (
        "'Manrope', 'Inter', 'Poppins', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "'Sora', 'Space Grotesk', 'Manrope', 'Inter', sans-serif",
    ),
    'inter': (
        "'Inter', 'Manrope', 'Poppins', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "'Space Grotesk', 'Sora', 'Inter', sans-serif",
    ),
    'poppins': (
        "'Poppins', 'Manrope', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "'Merriweather', 'Poppins', Georgia, serif",
    ),
    'system': (
        "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    ),
}


def _normalize_font_size(value, default=100):
    allowed = {choice[0] for choice in Profile.UI_FONT_SIZE_CHOICES}
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default

    if normalized not in allowed:
        normalized = default

    factor = (Decimal(normalized) / Decimal('100')).quantize(
        Decimal('0.001'),
        rounding=ROUND_HALF_UP,
    )
    factor_display = format(factor, 'f')
    if '.' in factor_display:
        factor_display = factor_display.rstrip('0').rstrip('.')

    return normalized, factor_display


def _normalize_font_weight(value, default=500):
    allowed = {choice[0] for choice in Profile.UI_FONT_WEIGHT_CHOICES}
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default

    if normalized not in allowed:
        normalized = default

    heading_weight = min(800, max(600, normalized + 100))
    return normalized, heading_weight


def _resolve_font_family(value, default='manrope'):
    selected = value if value in _FONT_FAMILY_STACKS else default
    body_stack, heading_stack = _FONT_FAMILY_STACKS[selected]
    return selected, body_stack, heading_stack


def _normalize_phone_for_tel(phone):
    if not phone:
        return ""
    cleaned = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned
    return f"+{cleaned}"


def _normalize_scale(value):
    value = value or 100
    value = max(50, min(int(value), 150))
    scale_factor = (Decimal(value) / Decimal('100')).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

    scale_factor_display = format(scale_factor, 'f')
    if '.' in scale_factor_display:
        scale_factor_display = scale_factor_display.rstrip('0').rstrip('.')

    return value, scale_factor_display, value != 100


def ui_scale_settings(request):
    """Expose global display settings so templates can adjust zoom and typography."""
    business_profile = None

    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        profile = getattr(user, 'profile', None)
        if profile is not None:
            # Prefer the primary business owner's profile when available so the
            # configuration applies uniformly across the entire tenant.
            try:
                business_user = profile.get_business_user()
            except AttributeError:
                business_user = None

            if business_user and hasattr(business_user, 'profile'):
                business_profile = business_user.profile
            else:
                business_profile = profile

    if business_profile is None:
        primary_username = getattr(settings, 'PRIMARY_BUSINESS_USERNAME', None)
        if primary_username:
            try:
                business_profile = Profile.objects.select_related('user').get(
                    user__username__iexact=primary_username
                )
            except Profile.DoesNotExist:
                business_profile = None

    if business_profile is None:
        portal_scale, portal_factor, portal_active = _normalize_scale(100)
        public_scale, public_factor, public_active = _normalize_scale(100)
        portal_font_size, portal_font_size_factor = _normalize_font_size(100)
        portal_font_weight, portal_heading_weight = _normalize_font_weight(500)
        portal_font_family, portal_font_family_css, portal_heading_font_family_css = _resolve_font_family('manrope')
        public_font_size, public_font_size_factor = _normalize_font_size(100)
        public_font_weight, public_heading_weight = _normalize_font_weight(500)
        public_font_family, public_font_family_css, public_heading_font_family_css = _resolve_font_family('manrope')
    else:
        portal_scale, portal_factor, portal_active = _normalize_scale(
            getattr(business_profile, 'ui_scale_percentage', 100)
        )
        public_scale, public_factor, public_active = _normalize_scale(
            getattr(business_profile, 'ui_scale_public_percentage', 100)
        )
        portal_font_size, portal_font_size_factor = _normalize_font_size(
            getattr(business_profile, 'ui_font_size_percentage', 100)
        )
        portal_font_weight, portal_heading_weight = _normalize_font_weight(
            getattr(business_profile, 'ui_font_weight', 500)
        )
        portal_font_family, portal_font_family_css, portal_heading_font_family_css = _resolve_font_family(
            getattr(business_profile, 'ui_font_family', 'manrope')
        )
        public_font_size, public_font_size_factor = _normalize_font_size(
            getattr(business_profile, 'ui_font_public_size_percentage', 100)
        )
        public_font_weight, public_heading_weight = _normalize_font_weight(
            getattr(business_profile, 'ui_font_public_weight', 500)
        )
        public_font_family, public_font_family_css, public_heading_font_family_css = _resolve_font_family(
            getattr(business_profile, 'ui_font_public_family', 'manrope')
        )

    return {
        'ui_scale_percentage': portal_scale,
        'ui_scale_factor': portal_factor,
        'ui_scale_is_active': portal_active,
        'ui_scale_public_percentage': public_scale,
        'ui_scale_public_factor': public_factor,
        'ui_scale_public_is_active': public_active,
        'ui_portal_font_size_percentage': portal_font_size,
        'ui_portal_font_size_factor': portal_font_size_factor,
        'ui_portal_font_family': portal_font_family,
        'ui_portal_font_family_css': portal_font_family_css,
        'ui_portal_heading_font_family_css': portal_heading_font_family_css,
        'ui_portal_font_weight': portal_font_weight,
        'ui_portal_heading_font_weight': portal_heading_weight,
        'ui_public_font_size_percentage': public_font_size,
        'ui_public_font_size_factor': public_font_size_factor,
        'ui_public_font_family': public_font_family,
        'ui_public_font_family_css': public_font_family_css,
        'ui_public_heading_font_family_css': public_heading_font_family_css,
        'ui_public_font_weight': public_font_weight,
        'ui_public_heading_font_weight': public_heading_weight,
    }


def analytics_settings(request):
    """
    Provide Google Analytics configuration to templates so tracking can be
    included conditionally and embed URLs can be displayed where needed.
    """
    measurement_id = getattr(settings, 'GOOGLE_ANALYTICS_MEASUREMENT_ID', '').strip()
    return {
        'google_analytics_measurement_id': measurement_id,
        'google_analytics_debug': getattr(settings, 'GOOGLE_ANALYTICS_DEBUG', False),
        'looker_studio_embed_url': getattr(settings, 'LOOKER_STUDIO_EMBED_URL', '').strip(),
        'analytics_enabled': bool(measurement_id),
    }


def maps_settings(request):
    """Expose Google Maps browser key to templates that need Maps JS features."""
    return {
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', '').strip(),
        'maps_enabled': bool(getattr(settings, 'GOOGLE_MAPS_API_KEY', '').strip()),
    }


def branding_defaults(request):
    """
    Provide safe branding fallbacks across internal templates.

    - business_name: falls back to settings.DEFAULT_BUSINESS_NAME
    - company_logo_url: falls back to settings.DEFAULT_LOGO_STATIC_PATH
    - business_contact_email: falls back to settings.DEFAULT_BUSINESS_EMAIL
    - business_contact_phone: falls back to settings.DEFAULT_BUSINESS_PHONE
    - business_contact_address: falls back to settings.DEFAULT_BUSINESS_ADDRESS

    View-provided context keys still take precedence over these defaults.
    """

    default_business_name = getattr(settings, "DEFAULT_BUSINESS_NAME", "Truck Zone") or "Truck Zone"
    default_logo_static_path = getattr(settings, "DEFAULT_LOGO_STATIC_PATH", "images/truck_zone_logo.png") or "images/truck_zone_logo.png"
    default_business_email = getattr(settings, "DEFAULT_BUSINESS_EMAIL", "info@example.com") or "info@example.com"
    default_business_phone = getattr(settings, "DEFAULT_BUSINESS_PHONE", "") or ""
    default_business_address = getattr(settings, "DEFAULT_BUSINESS_ADDRESS", "") or ""
    default_business_hours = getattr(settings, "DEFAULT_BUSINESS_HOURS", "") or ""
    default_logo_url = static(default_logo_static_path)

    user = getattr(request, "user", None)
    profile = getattr(user, "profile", None) if getattr(user, "is_authenticated", False) else None

    # Business name fallback: prefer profile.company_name when set, otherwise default.
    resolved_business_name = (
        getattr(profile, "company_name", None) if profile else None
    ) or default_business_name

    # Logo fallback: prefer profile logo when available (respects show_logo), otherwise static default.
    resolved_logo_url = default_logo_url
    if profile is not None:
        try:
            from .utils import resolve_company_logo_url  # local import to avoid heavy imports at startup

            resolved_logo_url = resolve_company_logo_url(profile, request=request) or default_logo_url
        except Exception:
            resolved_logo_url = default_logo_url

    resolved_contact_email = getattr(profile, "company_email", None) if profile else None
    resolved_contact_phone = getattr(profile, "company_phone", None) if profile else None
    resolved_contact_address = getattr(profile, "company_address", None) if profile else None
    resolved_contact_phone_display = resolved_contact_phone or default_business_phone

    return {
        "default_business_name": default_business_name,
        "default_business_email": default_business_email,
        "default_business_phone": default_business_phone,
        "default_business_address": default_business_address,
        "default_business_hours": default_business_hours,
        "default_company_logo_url": default_logo_url,
        "business_name": resolved_business_name,
        "company_logo_url": resolved_logo_url,
        "business_contact_email": resolved_contact_email or default_business_email,
        "business_contact_phone": resolved_contact_phone_display,
        "business_contact_phone_tel": _normalize_phone_for_tel(resolved_contact_phone_display),
        "business_contact_address": resolved_contact_address or default_business_address,
        "business_hours": default_business_hours,
    }


def cart_summary(request):
    """Expose cart item count for storefront navigation."""

    customer_account = None
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        try:
            customer_account = user.customer_portal
        except ObjectDoesNotExist:
            customer_account = None

    if not customer_account:
        return {
            "cart_item_count": 0,
        }

    store_owner = get_storefront_owner(request)
    if not store_owner:
        return {
            "cart_item_count": 0,
        }

    item_count = StorefrontCartItem.objects.filter(
        customer=customer_account,
        store_owner=store_owner,
    ).aggregate(total=Sum("quantity"))["total"]
    item_count = int(item_count or 0)

    return {
        "cart_item_count": max(item_count, 0),
    }


def customer_portal_context(request):
    """Expose the logged-in customer portal account, if any."""

    customer_account = None
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        try:
            customer_account = user.customer_portal
        except ObjectDoesNotExist:
            customer_account = None

    return {
        "customer_account": customer_account,
    }


def storefront_location_context(request):
    """Expose storefront location options and the current selection."""

    root_user = resolve_storefront_root_user(request)
    profiles = list(get_storefront_profiles(root_user)) if root_user else []
    selected_owner = get_storefront_owner(request, fallback_owner=root_user)
    selected_profile = None

    if profiles and selected_owner:
        for profile in profiles:
            if profile.user_id == selected_owner.id:
                selected_profile = profile
                break

    if not selected_profile and profiles:
        selected_profile = profiles[0]

    return {
        "storefront_locations": profiles,
        "storefront_selected_profile": selected_profile,
        "storefront_selected_owner": selected_owner,
        "storefront_has_multiple_locations": len(profiles) > 1,
    }


def storefront_nav_context(request):
    """Expose storefront category/brand navigation data for public menus."""

    default_owner = get_default_store_owner()
    store_owner = get_storefront_owner(request) or default_owner
    if not store_owner:
        return {
            "nav_categories": [],
            "nav_brand_logos": [],
        }

    def build_categories(owner):
        if not owner:
            return []
        product_user_ids = get_product_user_ids(owner)
        category_flags = resolve_storefront_category_flags(request, owner)
        show_empty_categories = category_flags["show_empty_categories"]
        available_products = None

        categories_qs = Category.objects.filter(is_active=True, parent__isnull=True)
        if show_empty_categories:
            if product_user_ids:
                categories_qs = categories_qs.filter(user__in=product_user_ids)
            else:
                categories_qs = categories_qs.filter(user=owner)
        else:
            available_products = Product.objects.filter(is_published_to_store=True)
            if product_user_ids:
                available_products = available_products.filter(user__in=product_user_ids)
            else:
                available_products = available_products.filter(user=owner)
            categories_qs = categories_qs.filter(products__in=available_products)

        categories = list(
            categories_qs.select_related("group", "parent")
            .distinct()
            .order_by("sort_order", "name")
        )
        if categories:
            return categories

        fallback_qs = Category.objects.filter(is_active=True)
        if show_empty_categories:
            if product_user_ids:
                fallback_qs = fallback_qs.filter(user__in=product_user_ids)
            else:
                fallback_qs = fallback_qs.filter(user=owner)
        else:
            if available_products is None:
                available_products = Product.objects.filter(is_published_to_store=True)
                if product_user_ids:
                    available_products = available_products.filter(user__in=product_user_ids)
                else:
                    available_products = available_products.filter(user=owner)
            fallback_qs = fallback_qs.filter(products__in=available_products)

        return list(
            fallback_qs.select_related("group", "parent")
            .distinct()
            .order_by("sort_order", "name")
        )

    def build_brand_logos(owner):
        if not owner:
            return []
        product_user_ids = get_product_user_ids(owner)
        brand_qs = ProductBrand.objects.filter(is_active=True)
        if product_user_ids:
            brand_qs = brand_qs.filter(user__in=product_user_ids)
        else:
            brand_qs = brand_qs.filter(user=owner)
        return list(brand_qs.order_by("sort_order", "name"))

    categories = build_categories(store_owner)
    brand_logos = build_brand_logos(store_owner)

    fallback_owner = default_owner
    if fallback_owner and fallback_owner != store_owner:
        if not categories:
            categories = build_categories(fallback_owner)
        if not brand_logos:
            brand_logos = build_brand_logos(fallback_owner)

    return {
        "nav_categories": categories,
        "nav_brand_logos": brand_logos,
    }
