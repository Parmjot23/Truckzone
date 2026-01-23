# utils.py
import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.storage import default_storage
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.templatetags.static import static
from urllib.parse import quote_plus
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    HTML = None
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.core.mail import send_mail
from django.urls import reverse
from decimal import Decimal
from django.db.models import (
    Sum,
    Value,
    F,
    Q,
    OuterRef,
    Subquery,
    Case,
    When,
    DecimalField,
    ExpressionWrapper,
    IntegerField,
)
from django.db.models.functions import Coalesce, Cast
from django.utils import timezone
from .models import (
    PendingInvoice,
    Product,
    ProductStock,
    UserStripeAccount,
    Profile,
    ConnectedBusinessGroup,
    CustomerCreditItem,
)
from .pdf_utils import apply_branding_defaults


def build_cc_list(*emails, exclude=None):
    """Return a deduped CC list, optionally excluding some recipients."""

    exclude_list = exclude or []
    exclude_set = {
        str(e).strip().lower()
        for e in exclude_list
        if e and str(e).strip()
    }

    result = []
    seen = set()
    for email in emails:
        if not email:
            continue
        email_str = str(email).strip()
        if not email_str:
            continue
        key = email_str.lower()
        if key in exclude_set or key in seen:
            continue
        seen.add(key)
        result.append(email_str)
    return result


def get_primary_business_username() -> str | None:
    """Return the configured username for the primary business account."""

    username = getattr(settings, "PRIMARY_BUSINESS_USERNAME", None)
    if not username:
        return None
    username = str(username).strip()
    return username or None


def get_primary_business_user():
    """Resolve the primary business owner ``User`` instance if configured."""

    username = get_primary_business_username()
    if not username:
        return None

    UserModel = get_user_model()
    try:
        return UserModel.objects.get(username__iexact=username)
    except UserModel.DoesNotExist:
        return None


def get_business_user(user):
    """Return the business owner associated with the provided user."""

    if not user:
        return None

    profile = getattr(user, "profile", None)
    if profile and hasattr(profile, "get_business_user"):
        business_user = profile.get_business_user()
        if business_user:
            return business_user

    return get_primary_business_user() or user


def _get_team_user_ids(business_user):
    if not business_user:
        return []
    user_ids = list(
        Profile.objects.filter(
            Q(user=business_user) | Q(business_owner=business_user)
        ).values_list("user_id", flat=True)
    )
    if business_user.id not in user_ids:
        user_ids.append(business_user.id)
    return user_ids


def get_business_user_ids(user):
    """Return user IDs associated with the same business owner."""

    if not user:
        return []

    business_user = get_business_user(user) or user
    if not business_user:
        return []

    user_ids = _get_team_user_ids(business_user)
    return user_ids or [business_user.id]


SHARE_SCOPE_CUSTOMERS = "customers"
SHARE_SCOPE_PRODUCTS = "products"
SHARE_SCOPE_PRODUCT_STOCK = "product_stock"


def get_connected_business_group(user):
    """Return the connected business group for a business user, if any."""

    if not user:
        return None

    business_user = get_business_user(user) or user
    if not business_user:
        return None

    return ConnectedBusinessGroup.objects.filter(members=business_user).first()


def get_shared_user_ids(user, scope):
    """Return user IDs for a shareable scope (customers/products)."""

    if not user:
        return []

    business_user = get_business_user(user) or user
    if not business_user:
        return []

    base_ids = set(_get_team_user_ids(business_user))
    group = get_connected_business_group(business_user)
    if not group:
        return list(base_ids)

    if scope == SHARE_SCOPE_CUSTOMERS and not group.share_customers:
        return list(base_ids)
    if scope == SHARE_SCOPE_PRODUCTS and not group.share_products:
        return list(base_ids)
    if scope == SHARE_SCOPE_PRODUCT_STOCK:
        if not group.share_products or not group.share_product_stock:
            return list(base_ids)

    member_ids = list(group.members.values_list("id", flat=True))
    if not member_ids:
        return list(base_ids)

    shared_profile_ids = Profile.objects.filter(
        Q(user_id__in=member_ids) | Q(business_owner_id__in=member_ids)
    ).values_list("user_id", flat=True)
    shared_ids = set(shared_profile_ids)
    shared_ids.update(member_ids)
    shared_ids.update(base_ids)
    return list(shared_ids)


def get_customer_user_ids(user):
    return get_shared_user_ids(user, SHARE_SCOPE_CUSTOMERS)


def get_product_user_ids(user):
    return get_shared_user_ids(user, SHARE_SCOPE_PRODUCTS)


def get_product_stock_user_ids(user):
    # Stock visibility follows the shared product list; stock values remain per-store.
    return get_product_user_ids(user)


def get_stock_owner(user):
    """Return the user that owns stock records for this account."""
    if not user:
        return None

    business_user = get_business_user(user) or user
    group = get_connected_business_group(business_user)

    profile_qs = Profile.objects.filter(
        occupation="parts_store",
        user__is_active=True,
        storefront_is_visible=True,
    )
    if group:
        member_ids = list(group.members.values_list("id", flat=True))
        if member_ids:
            profile_qs = profile_qs.filter(user_id__in=member_ids)
        else:
            profile_qs = Profile.objects.none()
    else:
        profile_qs = profile_qs.filter(Q(user=business_user) | Q(business_owner=business_user))
    profile_user_ids = set(profile_qs.values_list("user_id", flat=True))
    if len(profile_user_ids) > 1 and user.id in profile_user_ids:
        return user

    return business_user


def get_store_user_ids(user):
    """Return user IDs scoped to a single store location."""
    if not user:
        return []
    store_owner = get_stock_owner(user) or user
    user_ids = _get_team_user_ids(store_owner)
    return user_ids or [store_owner.id]


def annotate_products_with_stock(queryset, user):
    """Attach store-specific stock levels to a Product queryset."""
    stock_user = get_stock_owner(user)
    if not stock_user:
        return queryset.annotate(
            stock_quantity=Value(0, output_field=IntegerField()),
            stock_reorder=Value(0, output_field=IntegerField()),
        )

    stock_qs = ProductStock.objects.filter(product_id=OuterRef("pk"), user_id=stock_user.id)
    return queryset.annotate(
        stock_quantity=Coalesce(
            Subquery(stock_qs.values("quantity_in_stock")[:1]),
            Value(0),
            output_field=IntegerField(),
        ),
        stock_reorder=Coalesce(
            Subquery(stock_qs.values("reorder_level")[:1]),
            Value(0),
            output_field=IntegerField(),
        ),
    )


def apply_stock_fields(products):
    """Copy annotated stock values onto Product instances for template use."""
    for product in products:
        if hasattr(product, "stock_quantity"):
            product.quantity_in_stock = product.stock_quantity
        if hasattr(product, "stock_reorder"):
            product.reorder_level = product.stock_reorder
    return products


def upsert_product_stock(product, user, *, quantity_in_stock=None, reorder_level=None):
    """Create/update per-store stock values for a product."""
    stock_user = get_stock_owner(user)
    if not stock_user or not product:
        return None

    defaults = {}
    if quantity_in_stock is not None:
        defaults["quantity_in_stock"] = int(quantity_in_stock)
    if reorder_level is not None:
        defaults["reorder_level"] = int(reorder_level)

    if not defaults:
        return None

    stock, _ = ProductStock.objects.update_or_create(
        product=product,
        user=stock_user,
        defaults=defaults,
    )
    return stock


def sync_workorder_assignments(workorder, mechanics, *, allow_submitted_removal=False):
    """Synchronize ``WorkOrderAssignment`` rows for a work order.

    Args:
        workorder: WorkOrder instance being updated.
        mechanics: Iterable of Mechanic instances selected for the work order.
        allow_submitted_removal: If ``True`` submitted assignments may be deleted.

    Returns:
        dict containing lists of created, retained, protected (not removed), and
        removed assignments along with the selected mechanic IDs. ``created`` and
        ``retained`` contain ``WorkOrderAssignment`` instances. ``protected``
        contains assignments that could not be removed because they were
        already submitted. ``removed`` contains metadata dictionaries describing
        the assignments that were deleted.
    """

    from .models import WorkOrderAssignment  # Local import to avoid circular refs

    mechanics = list(mechanics or [])
    selected_ids = []
    seen = set()
    ordered_mechanics = []
    for mechanic in mechanics:
        mechanic_id = getattr(mechanic, "pk", None)
        if not mechanic_id or mechanic_id in seen:
            continue
        seen.add(mechanic_id)
        selected_ids.append(mechanic_id)
        ordered_mechanics.append(mechanic)

    existing = {
        assignment.mechanic_id: assignment
        for assignment in workorder.assignments.select_related("mechanic")
    }

    created = []
    retained = []
    protected = []
    removed = []

    for mechanic in ordered_mechanics:
        assignment = existing.get(mechanic.pk)
        if assignment:
            retained.append(assignment)
            continue
        assignment = WorkOrderAssignment.objects.create(
            workorder=workorder,
            mechanic=mechanic,
        )
        created.append(assignment)

    for mechanic_id, assignment in existing.items():
        if mechanic_id in seen:
            continue
        if assignment.submitted and not allow_submitted_removal:
            protected.append(assignment)
            continue
        removed.append(
            {
                "mechanic_id": mechanic_id,
                "mechanic_name": getattr(assignment.mechanic, "name", ""),
                "submitted": assignment.submitted,
            }
        )
        assignment.delete()

    return {
        "created": created,
        "retained": retained,
        "protected": protected,
        "removed": removed,
        "selected_ids": selected_ids,
    }


def resolve_company_logo_url(profile, *, request=None, for_pdf=False):
    """Return a URL/path for the company logo with a static fallback.

    Args:
        profile: Profile object that may contain a ``company_logo``.
        request: Optional request used to build absolute URLs for HTML/email.
        for_pdf: When ``True`` returns a ``file://`` path suitable for WeasyPrint.

    The function respects the ``show_logo`` flag. When no custom logo is
    available but ``show_logo`` is enabled, it falls back to the bundled
    default business logo (``static/images/truck_zone_logo.png`` by default).
    """

    if not getattr(profile, "show_logo", True):
        return ""

    logo_field = getattr(profile, "company_logo", None)

    if logo_field:
        logo_name = logo_field.name
        if for_pdf:
            try:
                if logo_name and default_storage.exists(logo_name):
                    try:
                        return "file://" + default_storage.path(logo_name)
                    except (NotImplementedError, AttributeError):
                        pass
            except Exception:
                # Storage backends without a local filesystem path (e.g., Cloudinary) still expose URLs
                pass
            try:
                if request is not None:
                    return request.build_absolute_uri(logo_field.url)
                return logo_field.url
            except Exception:
                return ""
        if request is not None:
            try:
                return request.build_absolute_uri(logo_field.url)
            except ValueError:
                return logo_field.url
        return logo_field.url

    static_path = getattr(settings, "DEFAULT_LOGO_STATIC_PATH", "images/truck_zone_logo.png") or "images/truck_zone_logo.png"

    if for_pdf:
        absolute_path = finders.find(static_path)
        if isinstance(absolute_path, (list, tuple)):
            absolute_path = absolute_path[0] if absolute_path else None
        if absolute_path:
            return "file://" + absolute_path
        return ""

    static_url = static(static_path)
    if request is not None:
        return request.build_absolute_uri(static_url)
    return static_url

def get_overdue_total_balance(user, term_days):
    """
    Returns the total overdue balance for a given user,
    treating term_days==0 as 'due on receipt' (i.e. <= today).
    """
    # 1) Base queryset: only unpaid invoices
    amount_field = DecimalField(max_digits=10, decimal_places=2)
    credit_amount_expr = Case(
        When(customer_credit__tax_included=True, then=Cast('amount', amount_field)),
        default=ExpressionWrapper(
            Cast('amount', amount_field) + Cast('tax_paid', amount_field),
            output_field=amount_field,
        ),
        output_field=amount_field,
    )
    credit_total = CustomerCreditItem.objects.filter(
        source_invoice=OuterRef('grouped_invoice_id')
    ).values('source_invoice').annotate(
        total=Coalesce(
            Sum(credit_amount_expr),
            Value(Decimal('0.00')),
            output_field=amount_field,
        )
    ).values('total')

    qs = PendingInvoice.objects.filter(
        is_paid=False,
        grouped_invoice__user=user
    ).annotate(
        total_paid=Coalesce(
            Sum('grouped_invoice__payments__amount'),
            Value(Decimal('0.00'))
        ),
        credit_total=Coalesce(
            Subquery(credit_total, output_field=amount_field),
            Value(Decimal('0.00')),
            output_field=amount_field,
        ),
        balance_due=ExpressionWrapper(
            F('grouped_invoice__total_amount') - F('total_paid') - F('credit_total'),
            output_field=amount_field,
        )
    )

    today = timezone.now().date()
    if term_days > 0:
        threshold = today - timedelta(days=term_days)
        lookup = 'lt'
    else:
        threshold = today
        lookup = 'lte'

    overdue_qs = qs.filter(
        **{f'grouped_invoice__date__{lookup}': threshold}
    )
    return overdue_qs.aggregate(total=Sum('balance_due'))['total'] or Decimal('0.00')

def generate_invoice_pdf(context):
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not available. PDF generation is disabled.")
    html_string = render_to_string('invoices/invoice.html', context)
    html = HTML(string=html_string)
    pdf = html.write_pdf()
    return pdf

def send_invoice_email(invoice, pdf_data, context):
    """Send invoice emails to the customer and the seller.

    This mirrors the behaviour of the standard invoice emailing flow
    used elsewhere in the application. A customer email with the PDF
    attached is sent using the ``invoice_email_customer.html`` template
    and a notification email is sent to the seller using the
    ``invoice_email_user.html`` template.
    """

    company_email = invoice.user.profile.company_email
    company_name = invoice.user.profile.company_name
    customer_email = invoice.bill_to_email
    customer = getattr(invoice, "customer", None)
    customer_cc_emails = customer.get_cc_emails() if customer else []

    # -------- Customer email --------
    customer_subject = f"Invoice from {company_name} - Invoice #{invoice.invoice_number}"
    customer_context = context.copy()
    customer_context['recipient_name'] = invoice.bill_to
    customer_context = apply_branding_defaults(customer_context)
    customer_body = render_to_string('emails/invoice_email_customer.html', customer_context)
    customer_cc = build_cc_list(
        company_email,
        *customer_cc_emails,
        exclude=[customer_email],
    )
    customer_message = EmailMessage(
        subject=customer_subject,
        body=customer_body,
        from_email=company_email,
        to=[customer_email] if customer_email else [],
        cc=customer_cc or None,
    )
    customer_message.content_subtype = 'html'
    customer_message.attach(
        f'Invoice_{invoice.invoice_number}.pdf',
        pdf_data,
        'application/pdf',
    )

    # -------- Seller notification --------
    user_subject = f"Invoice #{invoice.invoice_number} sent to {invoice.bill_to}"
    user_context = {
        'invoice': invoice,
        'customer': invoice.bill_to,
        'customer_email': invoice.bill_to_email,
        'company_name': company_name,
        'profile': invoice.user.profile,
        'total_amount': context.get('total_amount'),
    }
    user_context = apply_branding_defaults(user_context)
    user_body = render_to_string('emails/invoice_email_user.html', user_context)
    user_message = EmailMessage(
        user_subject,
        user_body,
        company_email,
        [invoice.user.email],
    )
    user_message.content_subtype = 'html'

    # Send both emails
    customer_message.send()
    user_message.send()

stripe.api_key = settings.STRIPE_SECRET_KEY

def verify_stripe_account(user):
    """
    Verifies that the user has a connected and active Stripe account.
    """
    try:
        user_stripe_account = UserStripeAccount.objects.get(user=user)
        if user_stripe_account.stripe_account_id:
            account = stripe.Account.retrieve(user_stripe_account.stripe_account_id)
            if account['charges_enabled']:
                print(f"Stripe account for {user.username} is active and ready for charges.")
                return True
            else:
                print(f"Stripe account for {user.username} is not enabled for charges.")
                return False
        else:
            print(f"No Stripe account ID found for {user.username}.")
            return False
    except UserStripeAccount.DoesNotExist:
        print(f"No Stripe account found for {user.username}.")
        return False
    except stripe.error.StripeError as e:
        print(f"Error verifying Stripe account: {str(e)}")
        return False

def format_currency(value):
    """Formats a number as currency."""
    try:
        return "${:,.2f}".format(float(value))
    except (ValueError, TypeError):
        return "$0.00"


def get_default_store_owner():
    """Return the business user that owns the public storefront."""

    UserModel = get_user_model()

    primary_user = get_primary_business_user()
    if primary_user:
        return primary_user

    configured_username = getattr(settings, "CUSTOMER_PORTAL_BUSINESS_USERNAME", None)
    if configured_username:
        try:
            return UserModel.objects.get(username=configured_username)
        except UserModel.DoesNotExist:
            pass

    product_owner_id = (
        Product.objects.order_by("id").values_list("user_id", flat=True).first()
    )
    if product_owner_id:
        return UserModel.objects.filter(id=product_owner_id).first()

    return UserModel.objects.filter(is_superuser=True).order_by("id").first()


def resolve_storefront_root_user(request=None, *, fallback_owner=None):
    """Return the primary business user used to scope storefront locations."""

    if request is not None:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            customer_account = getattr(user, "customer_portal", None)
            if customer_account and getattr(customer_account, "user", None):
                return get_business_user(customer_account.user)
            return get_business_user(user)

    return fallback_owner or get_default_store_owner()


def get_storefront_profiles(root_user):
    """Return profiles that should appear as selectable storefront locations."""

    if not root_user:
        return Profile.objects.none()

    base_qs = Profile.objects.select_related("user").filter(
        occupation="parts_store",
        user__is_active=True,
        storefront_is_visible=True,
    )
    group = get_connected_business_group(root_user)
    if group:
        member_ids = list(group.members.values_list("id", flat=True))
        if not member_ids:
            return Profile.objects.none()
        return base_qs.filter(user_id__in=member_ids).order_by("company_name", "user__username")

    linked_qs = base_qs.filter(Q(user=root_user) | Q(business_owner=root_user))
    linked_count = linked_qs.count()
    if linked_count > 1:
        return linked_qs.order_by("company_name", "user__username")

    root_profile = getattr(root_user, "profile", None)
    root_company = (getattr(root_profile, "company_name", "") or "").strip()
    if root_company:
        fallback_qs = base_qs.filter(company_name__iexact=root_company)
        fallback_count = fallback_qs.count()
        if fallback_count > linked_count:
            return fallback_qs.order_by("company_name", "user__username")

    return linked_qs.order_by("company_name", "user__username")


def get_storefront_owner(request=None, *, fallback_owner=None):
    """Return the selected storefront owner based on session or defaults."""

    root_user = resolve_storefront_root_user(request, fallback_owner=fallback_owner)
    profiles = list(get_storefront_profiles(root_user)) if root_user else []

    if not profiles:
        return root_user or fallback_owner or get_default_store_owner()

    allowed_ids = {profile.user_id for profile in profiles}
    selected_id = None
    if request is not None:
        selected_id = request.session.get("storefront_owner_id")
    if selected_id is not None:
        try:
            selected_id = int(selected_id)
        except (TypeError, ValueError):
            selected_id = None

    if selected_id in allowed_ids:
        for profile in profiles:
            if profile.user_id == selected_id:
                return profile.user

    if root_user and root_user.id in allowed_ids:
        return root_user

    return profiles[0].user


def resolve_storefront_price_flags(request, owner=None):
    """Return storefront price visibility flags for guests vs signed-in customers."""

    customer_account = (
        getattr(request.user, 'customer_portal', None)
        if getattr(request, 'user', None) and request.user.is_authenticated
        else None
    )
    if customer_account:
        return {
            'hero': True,
            'featured': True,
            'catalog': True,
        }

    owner = owner or get_storefront_owner(request) or get_default_store_owner()
    profile = getattr(owner, 'profile', None) if owner else None
    return {
        'hero': bool(profile and getattr(profile, 'storefront_show_prices_hero', False)),
        'featured': bool(profile and getattr(profile, 'storefront_show_prices_featured', False)),
        'catalog': bool(profile and getattr(profile, 'storefront_show_prices_catalog', False)),
    }


def resolve_storefront_category_flags(request, owner=None):
    """Return storefront category visibility flags for guests and customers."""

    owner = owner or get_storefront_owner(request) or get_default_store_owner()
    profile = getattr(owner, 'profile', None) if owner else None
    return {
        'show_empty_categories': bool(
            getattr(profile, 'storefront_show_empty_categories', True) if profile else True
        ),
    }


def is_parts_store_business(owner=None):
    """Return True when the storefront owner's occupation is parts_store."""

    owner = owner or get_default_store_owner()
    occupation = (
        getattr(getattr(owner, "profile", None), "occupation", "") or ""
    ).strip().lower()
    return occupation == "parts_store"

def calculate_next_occurrence(current_date, frequency):
    if not current_date or not frequency:
        return None
    if frequency == 'daily':
        return current_date + timedelta(days=1)
    elif frequency == 'weekly':
        return current_date + timedelta(weeks=1)
    elif frequency == 'biweekly':
        return current_date + timedelta(weeks=2)
    elif frequency == 'monthly':
        return current_date + relativedelta(months=1)
    elif frequency == 'quarterly':
        return current_date + relativedelta(months=3)
    elif frequency == 'yearly':
        return current_date + relativedelta(years=1)
    else:
        return None

import logging
logger = logging.getLogger(__name__)

def _resolve_site_url():
    site_url = getattr(settings, "SITE_URL", None)
    if site_url is None:
        return ""
    site_url = str(site_url).strip()
    return site_url.rstrip("/")


def _build_assignment_absolute_url(assignment, *, request=None):
    relative_url = reverse('accounts:mechanic_fill_workorder', args=[assignment.assignment_token])
    if request is not None:
        return request.build_absolute_uri(relative_url)
    site_url = _resolve_site_url()
    if site_url:
        if relative_url.startswith('/'):
            return f"{site_url}{relative_url}"
        return f"{site_url}/{relative_url}"
    logger.warning("SITE_URL is not configured; using relative mechanic work order link.")
    return relative_url


def _build_road_service_map_link(workorder):
    lat = getattr(workorder, "road_location_lat", None)
    lng = getattr(workorder, "road_location_lng", None)
    if lat is not None and lng is not None:
        coords = f"{lat},{lng}"
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(coords)}"
    location = (getattr(workorder, "road_location", "") or "").strip()
    if location:
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(location)}"
    return ""


def notify_mechanic_assignment(workorder, assignment, *, request=None):
    try:
        logger.info("Sending email to %s for WorkOrder #%s", assignment.mechanic.email, workorder.id)
        absolute_url = _build_assignment_absolute_url(assignment, request=request)
        subject = f"New Work Order Assignment #{workorder.id}"
        road_details = ""
        if getattr(workorder, "road_service", False):
            location = (getattr(workorder, "road_location", "") or "").strip()
            map_link = _build_road_service_map_link(workorder)
            contact_phone = (getattr(workorder, "road_contact_phone", "") or "").strip()
            if not contact_phone and getattr(workorder, "customer", None):
                contact_phone = (getattr(workorder.customer, "phone_number", "") or "").strip()
            road_lines = ["Road service: YES"]
            if location:
                road_lines.append(f"Location: {location}")
            if map_link:
                road_lines.append(f"Map: {map_link}")
            if contact_phone:
                road_lines.append(f"Customer phone: {contact_phone}")
            road_details = "\n" + "\n".join(road_lines)
        message = (
            f"Hello {assignment.mechanic.name},\n\n"
            f"You have been assigned to Work Order #{workorder.id}.\n"
            f"{road_details}\n"
            f"Please fill in your section using the following link:\n\n{absolute_url}\n\n"
            "Thank you,\nYour Work Order System"
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [assignment.mechanic.email],
            fail_silently=False,
        )
        logger.info("Email sent to %s", assignment.mechanic.email)
    except OSError as e:
        logger.error("OSError during send_mail: %s", e)
    except Exception as e:
        logger.error("Unexpected error during email sending: %s", e)


def notify_mechanic_rework(workorder, assignment, *, request=None):
    try:
        logger.info(
            "Sending urgent rework email to %s for WorkOrder #%s",
            assignment.mechanic.email,
            workorder.id,
        )
        absolute_url = _build_assignment_absolute_url(assignment, request=request)
        subject = f"URGENT: Updates requested for Work Order #{workorder.id}"
        instructions = (assignment.rework_instructions or '').strip()
        instructions_text = instructions if instructions else 'Please review the updated instructions in the portal.'
        requested_time = assignment.rework_requested_at
        if requested_time:
            requested_stamp = timezone.localtime(requested_time).strftime('%B %d, %Y at %I:%M %p')
            requested_line = f"Requested on: {requested_stamp}\n\n"
        else:
            requested_line = ''
        message = (
            f"Hello {assignment.mechanic.name},\n\n"
            f"The business has requested urgent updates for Work Order #{workorder.id}.\n"
            f"{requested_line}Updated instructions:\n{instructions_text}\n\n"
            f"Re-open the work order and make the required changes here:\n{absolute_url}\n\n"
            "Please address this request as soon as possible."
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [assignment.mechanic.email],
            fail_silently=False,
        )
    except OSError as e:
        logger.error("OSError during urgent rework email send: %s", e)
    except Exception as e:
        logger.error("Unexpected error during urgent rework email send: %s", e)


def _resolve_customer_recipients(workorder):
    customer = getattr(workorder, "customer", None)
    primary = (getattr(workorder, "bill_to_email", None) or (customer.email if customer else None))
    if not primary and customer and getattr(customer, "portal_user", None):
        primary = customer.portal_user.email or None
    cc_recipients = build_cc_list(*(customer.get_cc_emails() if customer else []), exclude=[primary])
    return primary, cc_recipients


def _format_workorder_customer_name(workorder):
    customer = getattr(workorder, "customer", None)
    return (customer.name if customer and customer.name else (workorder.bill_to or "Customer"))


def _format_workorder_unit_label(workorder):
    unit_no = (getattr(workorder, "unit_no", None) or "").strip()
    if not unit_no and getattr(workorder, "vehicle", None):
        unit_no = (getattr(workorder.vehicle, "unit_number", None) or "").strip()
    return unit_no


def _format_workorder_mechanic_names(workorder):
    assignments = workorder.assignments.select_related("mechanic")
    names = [assignment.mechanic.name for assignment in assignments if assignment.mechanic]
    return ", ".join(sorted({name for name in names if name}))


def notify_customer_work_started(workorder):
    recipient, cc_recipients = _resolve_customer_recipients(workorder)
    if not recipient:
        logger.info("Skipping work started email; no customer email for WorkOrder #%s", workorder.id)
        return

    business_name = getattr(getattr(workorder.user, "profile", None), "company_name", None) or "Your Service Team"
    unit_no = _format_workorder_unit_label(workorder) or "N/A"
    mechanic_names = _format_workorder_mechanic_names(workorder) or "To be assigned"
    description = (getattr(workorder, "description", None) or "No description provided.").strip()
    workorder_number = workorder.workorder_number or f"#{workorder.id}"

    subject = f"Work started on your vehicle - Work Order {workorder_number}"
    message = (
        f"Hello {_format_workorder_customer_name(workorder)},\n\n"
        f"We have started work on your vehicle (Unit {unit_no}).\n\n"
        f"Work Order: {workorder_number}\n"
        f"Description: {description}\n"
        f"Assigned mechanic(s): {mechanic_names}\n\n"
        "We will let you know when the work is completed.\n\n"
        f"Thank you,\n{business_name}"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            cc=cc_recipients,
            fail_silently=False,
        )
        logger.info("Work started email sent to %s for WorkOrder #%s", recipient, workorder.id)
    except OSError as e:
        logger.error("OSError during work started email send: %s", e)
    except Exception as e:
        logger.error("Unexpected error during work started email send: %s", e)


def notify_customer_work_completed(workorder):
    recipient, cc_recipients = _resolve_customer_recipients(workorder)
    if not recipient:
        logger.info("Skipping work completed email; no customer email for WorkOrder #%s", workorder.id)
        return

    business_name = getattr(getattr(workorder.user, "profile", None), "company_name", None) or "Your Service Team"
    unit_no = _format_workorder_unit_label(workorder) or "N/A"
    mechanic_names = _format_workorder_mechanic_names(workorder) or "Assigned team"
    description = (getattr(workorder, "description", None) or "No description provided.").strip()
    workorder_number = workorder.workorder_number or f"#{workorder.id}"

    subject = f"Work completed - Work Order {workorder_number}"
    message = (
        f"Hello {_format_workorder_customer_name(workorder)},\n\n"
        f"Your work order is complete. Vehicle Unit {unit_no} is ready for pickup.\n\n"
        f"Work Order: {workorder_number}\n"
        f"Description: {description}\n"
        f"Assigned mechanic(s): {mechanic_names}\n\n"
        "Your invoice will be sent shortly. If you have any questions, please contact us.\n\n"
        f"Thank you,\n{business_name}"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            cc=cc_recipients,
            fail_silently=False,
        )
        logger.info("Work completed email sent to %s for WorkOrder #%s", recipient, workorder.id)
    except OSError as e:
        logger.error("OSError during work completed email send: %s", e)
    except Exception as e:
        logger.error("Unexpected error during work completed email send: %s", e)
