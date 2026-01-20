from django.conf import settings
from django.contrib.auth import logout
from django.http import Http404
from django.urls import NoReverseMatch, reverse
from django.utils.deprecation import MiddlewareMixin

from .activity import set_current_actor, clear_current_actor
from .utils import get_business_user


class TrialPeriodMiddleware(MiddlewareMixin):
    """No-op middleware now that subscription requirements have been removed."""

    def process_request(self, request):
        return None


class BusinessImpersonationMiddleware(MiddlewareMixin):
    """Ensure all staff activity is scoped to the primary business account.

    For approved staff members we impersonate the primary business owner for
    the duration of the request so all create/update operations use the same
    ``user`` reference. The authenticated account is preserved on
    ``request.actual_user`` so downstream logic (e.g. activity logging) can
    still identify the acting staff member.
    """

    def process_request(self, request):
        # Reset any previous actor context at the beginning of the request
        clear_current_actor()

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            request.actual_user = None
            return None

        # Preserve the authenticated account for auditing purposes
        request.actual_user = user

        profile = getattr(user, "profile", None)
        if not profile or not getattr(profile, "is_business_admin", False):
            return None

        if not getattr(profile, "admin_approved", False):
            return None

        business_user = get_business_user(user)
        if business_user and business_user != user:
            request.user = business_user

        set_current_actor(request.actual_user)
        return None

    def process_response(self, request, response):
        clear_current_actor()
        return response


class CustomerPortalIsolationMiddleware(MiddlewareMixin):
    """Prevent non-business portals (customer, mechanic, supplier) from hitting business routes."""

    def process_request(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        path = request.path_info or "/"

        portal = None
        if getattr(user, "customer_portal", None):
            portal = "customer"
        elif getattr(user, "mechanic_portal", None):
            portal = "mechanic"
        elif getattr(user, "supplier_portal", None):
            portal = "supplier"
        elif getattr(user, "accountant_portal", None):
            portal = "accountant"

        # Only enforce for non-business portal users
        if not portal:
            return None

        # Let portal users reach the login page so they can switch accounts cleanly.
        login_url = None
        try:
            login_url = reverse("accounts:login")
        except NoReverseMatch:
            login_url = "/login/"

        if login_url and path == login_url:
            logout(request)
            return None

        allowed_prefixes = [
            getattr(settings, "STATIC_URL", None) or "/static/",
            getattr(settings, "MEDIA_URL", None) or "/media/",
        ]
        allowed_exact = {reverse("accounts:logout")}
        if login_url:
            allowed_exact.add(login_url)
        for auth_route in (
            "accounts:password_reset",
            "accounts:password_reset_done",
            "accounts:password_reset_complete",
        ):
            try:
                allowed_exact.add(reverse(auth_route))
            except NoReverseMatch:
                pass

        # Allow public marketing pages regardless of the active portal so users can
        # safely browse or land on them after logging out.
        public_route_names = [
            "accounts:public_home",
            "accounts:public_about",
            "accounts:public_services",
            "accounts:public_contact",
            "accounts:public_booking",
            "accounts:booking_slots",
            "accounts:public_emergency",
            "accounts:public_contact_form",
            "accounts:service_engine",
            "accounts:service_transmission",
            "accounts:service_brakes",
            "accounts:service_electrical",
            "accounts:service_maintenance",
            "accounts:service_dot",
            "accounts:service_dpf",
        ]

        for route_name in public_route_names:
            try:
                allowed_exact.add(reverse(route_name))
            except NoReverseMatch:
                # Skip routes that are not configured in this deployment.
                pass

        if portal == "customer":
            allowed_prefixes.append("/store/")
            allowed_exact.add(reverse("accounts:customer_dashboard"))
        elif portal == "mechanic":
            allowed_prefixes.append("/mechanic/")
            allowed_prefixes.append("/workorders/fill/")
            allowed_exact.add(reverse("accounts:mechanic_portal_dashboard"))
        elif portal == "supplier":
            allowed_prefixes.append("/supplier/")
            # Supplier portal default dashboard
            try:
                allowed_exact.add(reverse("accounts:supplier_dashboard"))
            except Exception:
                pass
        elif portal == "accountant":
            allowed_prefixes.append("/accountant-portal/")
            try:
                allowed_exact.add(reverse("accounts:accountant_portal_dashboard"))
            except Exception:
                pass
            accountant_profile = getattr(user, "accountant_portal", None)
            if accountant_profile and getattr(accountant_profile, "accountant_access_level", "") in ("full", "read_only"):
                try:
                    allowed_exact.add(reverse("accounts:income_details_by_date"))
                except Exception:
                    pass
                try:
                    allowed_exact.add(reverse("accounts:expense_details_by_date"))
                except Exception:
                    pass
                allowed_prefixes.append("/grouped-invoices/")
                allowed_prefixes.append("/mech-expenses/")

        if path in allowed_exact:
            return None

        for prefix in allowed_prefixes:
            if prefix and path.startswith(prefix):
                return None

        # Deny everything else to keep business templates inaccessible.
        raise Http404
