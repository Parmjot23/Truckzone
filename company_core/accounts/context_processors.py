from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ObjectDoesNotExist

from django.conf import settings
from django.templatetags.static import static

from .models import Profile
from .utils import (
    get_storefront_owner,
    get_storefront_profiles,
    resolve_storefront_root_user,
)


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
    """Expose UI scale information so templates can adjust zoom globally."""
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
    else:
        portal_scale, portal_factor, portal_active = _normalize_scale(
            getattr(business_profile, 'ui_scale_percentage', 100)
        )
        public_scale, public_factor, public_active = _normalize_scale(
            getattr(business_profile, 'ui_scale_public_percentage', 100)
        )

    return {
        'ui_scale_percentage': portal_scale,
        'ui_scale_factor': portal_factor,
        'ui_scale_is_active': portal_active,
        'ui_scale_public_percentage': public_scale,
        'ui_scale_public_factor': public_factor,
        'ui_scale_public_is_active': public_active,
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

    cart = getattr(request, "session", {}).get("cart", {}) or {}
    item_count = 0
    for qty in cart.values():
        try:
            item_count += int(qty)
        except (TypeError, ValueError):
            continue

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
