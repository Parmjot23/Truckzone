import decimal  # Import the decimal module
from decimal import ROUND_HALF_UP  # Import specific constants if needed
from decimal import InvalidOperation
from django.db import models, transaction, IntegrityError, DatabaseError
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.utils.text import slugify
import re
from django.core.exceptions import ValidationError
from django.conf import settings
import stripe
from django.utils import timezone
from datetime import date
import datetime
from decimal import Decimal
import logging
import uuid
from django.core.validators import RegexValidator, validate_email, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.urls import reverse
from datetime import timedelta
from django.db.models import F, Q, Sum, ExpressionWrapper, DecimalField, Max
from django.db.models.functions import Lower
from cryptography.fernet import Fernet, InvalidToken



stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)

# Constants
PROVINCE_CHOICES = [
    ('AB', 'Alberta'),
    ('BC', 'British Columbia'),
    ('MB', 'Manitoba'),
    ('NB', 'New Brunswick'),
    ('NL', 'Newfoundland and Labrador'),
    ('NT', 'Northwest Territories'),
    ('NS', 'Nova Scotia'),
    ('NU', 'Nunavut'),
    ('ON', 'Ontario'),
    ('PE', 'Prince Edward Island'),
    ('QC', 'Quebec'),
    ('SK', 'Saskatchewan'),
    ('YT', 'Yukon'),
    ('CU', 'Custom'),
]

PROVINCE_TAX_RATES = {
    'AB': 0.05,
    'BC': 0.12,
    'MB': 0.13,
    'NB': 0.15,
    'NL': 0.15,
    'NT': 0.05,
    'NS': 0.15,
    'NU': 0.05,
    'ON': 0.13,
    'PE': 0.15,
    'QC': 0.14975,
    'SK': 0.11,
    'YT': 0.05,
    'CU': 0,
}

PROVINCE_TAX_COMPONENTS = {
    'AB': (Decimal('0.05'),),
    'BC': (Decimal('0.05'), Decimal('0.07')),
    'MB': (Decimal('0.05'), Decimal('0.08')),
    'NB': (Decimal('0.15'),),
    'NL': (Decimal('0.15'),),
    'NT': (Decimal('0.05'),),
    'NS': (Decimal('0.15'),),
    'NU': (Decimal('0.05'),),
    'ON': (Decimal('0.13'),),
    'PE': (Decimal('0.15'),),
    'QC': (Decimal('0.05'), Decimal('0.09975')),
    'SK': (Decimal('0.05'), Decimal('0.06')),
    'YT': (Decimal('0.05'),),
}

PROVINCE_DISPLAY_MAP = dict(PROVINCE_CHOICES)

DEFAULT_PUBLIC_SERVICE_TYPES = [
    ("engine", "Engine Diagnostics & Repair"),
    ("transmission", "Transmission Services"),
    ("brakes", "Brake System Services"),
    ("electrical", "Electrical Systems"),
    ("dpf", "DPF & Emissions Service"),
    ("maintenance", "Preventive Maintenance"),
    ("dot", "DriveON (MTO) Inspections"),
    ("emergency", "Emergency Service"),
    ("other", "Other"),
]


def _build_public_service_types():
    raw_types = getattr(settings, "PUBLIC_SERVICE_TYPES", None)
    if not raw_types:
        return list(DEFAULT_PUBLIC_SERVICE_TYPES)

    choices = []
    seen_values = set()

    for entry in raw_types:
        value = ""
        label = ""

        if isinstance(entry, dict):
            label = entry.get("label") or entry.get("name") or entry.get("title") or ""
            value = entry.get("value") or entry.get("code") or ""
        elif isinstance(entry, (list, tuple)):
            if len(entry) >= 2:
                value, label = entry[:2]
            elif len(entry) == 1:
                label = entry[0]
        else:
            label = entry

        label = str(label).strip() if label is not None else ""
        value = str(value).strip() if value is not None else ""

        if not label and not value:
            continue
        if not label:
            label = value
        if not value:
            value = slugify(label).replace("-", "_")
        if not value:
            continue

        value = value[:32]
        if value in seen_values:
            continue
        seen_values.add(value)
        choices.append((value, label))

    return choices or list(DEFAULT_PUBLIC_SERVICE_TYPES)


PUBLIC_SERVICE_TYPES = _build_public_service_types()

TERM_CHOICES = {
        'due_on_receipt': 0,
        'net_2': 2,
        'net_7': 7,
        'net_15': 15,
        'net_30': 30,
        'net_45': 45,
    }

PAYMENT_LINK_PROVIDER_STRIPE = "stripe"
PAYMENT_LINK_PROVIDER_CLOVER = "clover"
PAYMENT_LINK_PROVIDER_NONE = "none"
PAYMENT_LINK_PROVIDER_CHOICES = [
    (PAYMENT_LINK_PROVIDER_STRIPE, "Stripe"),
    (PAYMENT_LINK_PROVIDER_CLOVER, "Clover"),
    (PAYMENT_LINK_PROVIDER_NONE, "None"),
]

qst_validator = RegexValidator(
    regex=r'^\d{10}RP\d{4}$',
    message="Invalid QST number format. Must be 10 digits followed by 'RP' and then 4 digits (e.g., 1234567890TQ0001)."
)


def ensure_decimal(value, default='0.00'):
    """Return a Decimal instance for the given value."""
    if isinstance(value, Decimal):
        return value
    if value in (None, ''):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)

def get_tax_components(province_code, custom_tax_rate=None):
    if province_code == 'CU':
        if custom_tax_rate is None:
            return ()
        custom_rate = ensure_decimal(custom_tax_rate)
        if custom_rate == Decimal('0.00'):
            return ()
        return (custom_rate,)

    components = PROVINCE_TAX_COMPONENTS.get(province_code)
    if components is not None:
        return components

    rate_value = PROVINCE_TAX_RATES.get(province_code, 0)
    rate_decimal = ensure_decimal(rate_value)
    if rate_decimal == Decimal('0.00'):
        return ()
    return (rate_decimal,)


def get_tax_component_rates(province_code, custom_tax_rate=None):
    return [float(rate) for rate in get_tax_components(province_code, custom_tax_rate=custom_tax_rate)]


def calculate_tax_components(amount, province_code, *, tax_included=False, custom_tax_rate=None):
    amount_dec = ensure_decimal(amount)
    components = get_tax_components(province_code, custom_tax_rate=custom_tax_rate)
    if not components:
        return [], Decimal('0.00'), amount_dec

    total_rate = sum(components, Decimal('0.00'))
    taxable_base = amount_dec
    if tax_included and total_rate:
        taxable_base = (amount_dec / (Decimal('1.00') + total_rate)).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    taxes = [
        (taxable_base * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        for rate in components
    ]
    total_tax = sum(taxes, Decimal('0.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if tax_included:
        taxable_base = (amount_dec - total_tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return taxes, total_tax, taxable_base


def calculate_tax_total(amount, province_code, *, tax_included=False, custom_tax_rate=None):
    return calculate_tax_components(
        amount,
        province_code,
        tax_included=tax_included,
        custom_tax_rate=custom_tax_rate,
    )[1]


class UserStripeAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    stripe_account_id = models.CharField(max_length=255, blank=True, null=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username

class Plan(models.Model):
    name = models.CharField(max_length=50)
    stripe_plan_id = models.CharField(max_length=100)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    business_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='team_profiles',
        help_text="Primary business account this profile belongs to.",
    )
    is_business_admin = models.BooleanField(
        default=False,
        help_text="Designates this profile as a member of the business staff.",
    )
    admin_approved = models.BooleanField(
        default=False,
        help_text="Indicates whether the staff account has been approved.",
    )
    stripe_terminal_location_id = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Stores Stripe Terminal Location ID for this user’s connected account"
    )
    terminal_enabled = models.BooleanField(
        default=False,
        help_text="Allow in-person payments via Stripe Terminal"
    )
    send_payment_link_email = models.BooleanField(
        default=True,
        verbose_name="Email payment link on invoice",
        help_text="Toggle whether the system should include an online payment link in outgoing emails."
    )
    payment_link_provider = models.CharField(
        max_length=20,
        choices=PAYMENT_LINK_PROVIDER_CHOICES,
        default=PAYMENT_LINK_PROVIDER_STRIPE,
        help_text="Select which provider to use when generating online payment links.",
    )
    company_name = models.CharField(max_length=100, blank=True, null=True)
    storefront_display_name = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Optional name shown to customers when selecting a store location.",
    )
    storefront_is_visible = models.BooleanField(
        default=True,
        help_text="Show this location in the storefront selector.",
    )
    company_address = models.TextField(blank=True, null=True)
    company_email = models.EmailField(max_length=254, blank=True, null=True)
    company_phone = models.TextField(blank=True, null=True)
    company_fax = models.CharField(max_length=50, blank=True, null=True)
    ACCOUNTANT_ACCESS_CHOICES = [
        ('full', 'Full access'),
        ('reports', 'Reports only'),
        ('read_only', 'Read only'),
    ]
    accountant_name = models.CharField(max_length=100, blank=True, null=True)
    accountant_firm = models.CharField(max_length=120, blank=True, null=True)
    accountant_email = models.EmailField(max_length=254, blank=True, null=True)
    accountant_phone = models.CharField(max_length=50, blank=True, null=True)
    accountant_access_level = models.CharField(
        max_length=20,
        choices=ACCOUNTANT_ACCESS_CHOICES,
        default='reports',
        blank=True,
    )
    accountant_timezone = models.CharField(max_length=50, blank=True, null=True)
    accountant_portal_user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accountant_portal',
        help_text="Login account for the accountant portal.",
    )
    gst_hst_number = models.CharField(max_length=50, blank=True, null=True)
    wsib_number = models.CharField(max_length=50, blank=True, null=True)
    company_logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)
    term = models.CharField(
        max_length=20,
        choices=[('due_on_receipt', 'Due on Receipt'),
            ('net_2', 'Due within 2 days'),
            ('net_7', 'Due within 7 days'),
            ('net_15', 'Due within 15 days'),
            ('net_30', 'Due within 30 days'),
            ('net_45', 'Due within 45 days')],
        default='net_30',
        help_text="Payment due in specified days or due on receipt"
    )
    show_note = models.BooleanField(default=True, help_text="Show note on the invoice")
    note = models.TextField(
        blank=True,
        null=True,
        default="Please ensure payment is made within the specified period to avoid any potential overdue charges.",
        help_text="Custom note for the invoice"
    )
    invoice_sequence_next = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Next invoice sequence number. Leave blank to keep automatic numbering.",
    )
    use_dynamic_note = models.BooleanField(
        default=False,
        help_text="Use an AI-generated dynamic note instead of a custom note."
    )
    occupation = models.CharField(
        max_length=50,
        choices=[
            ('truck_mechanic', 'Truck Mechanic'),
            ('towing', 'Towing'),
            ('parts_store', 'Parts Store'),
        ],
    )

    street_address = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES, default='ON')
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    invoice_header_color = models.CharField(max_length=7, default='#007bff')
    invoice_font_size = models.IntegerField(default=16)
    show_logo = models.BooleanField(default=True)
    show_address = models.BooleanField(default=True)
    UI_SCALE_CHOICES = [
        (150, 'Maximum (150%)'),
        (120, 'Extra Large (120%)'),
        (110, 'Large (110%)'),
        (100, 'Default (100%)'),
        (95, 'Comfortable (95%)'),
        (90, 'Compact (90%)'),
        (85, 'Extra Compact (85%)'),
        (80, 'Ultra Compact (80%)'),
        (75, 'Tighter (75%)'),
        (70, 'Micro (70%)'),
        (65, 'Mini (65%)'),
        (60, 'Minimum (60%)'),
    ]
    ui_scale_percentage = models.PositiveIntegerField(
        default=100,
        choices=UI_SCALE_CHOICES,
        help_text="Controls how much the portal and dashboard interfaces should be scaled.",
    )
    ui_scale_public_percentage = models.PositiveIntegerField(
        default=100,
        choices=UI_SCALE_CHOICES,
        help_text="Controls how much the public website pages should be scaled.",
    )
    storefront_show_prices_hero = models.BooleanField(
        default=False,
        help_text="Show prices to guests in the homepage hero section.",
    )
    storefront_show_prices_featured = models.BooleanField(
        default=False,
        help_text="Show prices to guests in featured product sections.",
    )
    storefront_show_prices_catalog = models.BooleanField(
        default=False,
        help_text="Show prices to guests across product listings and details.",
    )
    storefront_show_empty_categories = models.BooleanField(
        default=True,
        help_text="Show category groups and categories even when no products are published.",
    )
    qr_code_font_scale = models.PositiveIntegerField(
        default=100,
        help_text="Scale percentage used to adjust QR code label font sizes.",
    )
    qr_show_name = models.BooleanField(
        default=True,
        help_text="Display the product name on generated QR code labels.",
    )
    qr_show_description = models.BooleanField(
        default=True,
        help_text="Display the product description on generated QR code labels.",
    )
    qr_show_sku = models.BooleanField(
        default=True,
        help_text="Display the product SKU on generated QR code labels.",
    )
    default_inventory_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Default profit margin percentage applied to inventory sale prices.",
    )
    trial_start_date = models.DateTimeField(null=True, blank=True)
    trial_end_date = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    deactivation_date = models.DateTimeField(blank=True, null=True)

    # Consent related fields
    consent_given = models.BooleanField(default=False)
    consent_date = models.DateTimeField(blank=True, null=True)
    consent_version = models.CharField(max_length=10, null=True, blank=True)
    activation_link_clicked = models.BooleanField(default=False)
    activation_date = models.DateTimeField(null=True, blank=True)

    interact_email = models.EmailField(
        max_length=254,
        blank=True,
        null=True,
        help_text="This email is used for asking users for payments."
    )

    qst_number = models.CharField(
        max_length=17,  # 10 digits + 'TQ' + 4 digits = 16 chars, 17 to be safe
        blank=True,
        null=True,
        validators=[qst_validator],
        help_text="Enter your QST number (e.g., 1234567890TQ0001) if your province is Quebec."
    )

    def save(self, *args, **kwargs):
        primary_username = getattr(settings, "PRIMARY_BUSINESS_USERNAME", None)
        if primary_username and self.user.username.lower() == primary_username.lower():
            self.business_owner = self.user
            self.is_business_admin = True
            self.admin_approved = True
        elif self.is_business_admin and not self.business_owner:
            if primary_username:
                try:
                    owner = User.objects.get(username__iexact=primary_username)
                    self.business_owner = owner
                except User.DoesNotExist:
                    pass
        if self.street_address and self.city and self.province and self.postal_code:
            self.company_address = f"{self.street_address},\n{self.city}, {self.province} {self.postal_code}"
        super(Profile, self).save(*args, **kwargs)

        if self.is_business_admin:
            desired_active = bool(self.admin_approved)
            if self.user.is_active != desired_active:
                User.objects.filter(pk=self.user.pk).update(is_active=desired_active)
                self.user.is_active = desired_active

    def get_business_user(self):
        if self.business_owner:
            return self.business_owner
        primary_username = getattr(settings, "PRIMARY_BUSINESS_USERNAME", None)
        if primary_username and self.user.username.lower() == primary_username.lower():
            return self.user
        return self.user

    @property
    def is_admin_active(self):
        return self.is_business_admin and self.admin_approved

    def get_tax_name(self):
        tax_names = {
            'AB': 'GST (AB) @ 5%',
            'BC': 'GST + PST (BC) @ 12%',
            'MB': 'GST + PST (MB) @ 13%',
            'NB': 'HST (NB) @ 15%',
            'NL': 'HST (NL) @ 15%',
            'NT': 'GST (NT) @ 5%',
            'NS': 'HST (NS) @ 15%',
            'NU': 'GST (NU) @ 5%',
            'ON': 'HST (ON) @ 13%',
            'PE': 'HST (PE) @ 15%',
            'QC': 'GST + QST (QC) @ 14.975%',
            'SK': 'GST + PST (SK) @ 11%',
            'YT': 'GST (YT) @ 5%',
        }
        return tax_names.get(self.province, 'GST/HST')

    def profile_completion(self):
        required_fields = [
            self.company_name,
            self.company_address,
            self.company_email,
            self.company_phone,
            self.gst_hst_number,
            self.company_logo,
            self.occupation,
            self.street_address,
            self.city,
            self.postal_code
        ]
        filled_fields = [field for field in required_fields if field]
        completion_percentage = int(len(filled_fields) / len(required_fields) * 100)
        return completion_percentage

    def has_active_subscription(self):
        if self.stripe_subscription_id:
            try:
                subscription = stripe.Subscription.retrieve(self.stripe_subscription_id)
                if subscription.status == 'active':
                    return True
            except stripe.error.StripeError:
                pass
        return False

    def is_trial_period_active(self):
        if self.trial_end_date:
            return self.trial_end_date > timezone.now()
        return False

    def can_access_premium_features(self):
        return self.has_active_subscription() or self.is_trial_period_active()

    @property
    def storefront_label(self):
        label = (self.storefront_display_name or "").strip()
        if label:
            return label
        label = (self.company_name or "").strip()
        if label:
            return label
        return self.user.get_full_name() or self.user.get_username()

    def __str__(self):
        return f"{self.user.username} Profile"


class ConnectedBusinessGroup(models.Model):
    name = models.CharField(max_length=120, blank=True)
    members = models.ManyToManyField(
        User,
        related_name="connected_business_groups",
        blank=True,
    )
    share_customers = models.BooleanField(
        default=True,
        help_text="Share customers (and related lists) across connected businesses.",
    )
    share_products = models.BooleanField(
        default=False,
        help_text="Share product lists across connected businesses.",
    )
    share_product_stock = models.BooleanField(
        default=True,
        help_text="Share stock on hand across connected businesses.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Connected business group"
        verbose_name_plural = "Connected business groups"

    def __str__(self):
        return self.name or f"Connected group #{self.pk}"


class Note(models.Model):
    # Title of the note
    title = models.CharField(max_length=255)

    # Content of the note
    content = models.TextField()

    # Automatically store when the note is created
    created_at = models.DateTimeField(auto_now_add=True)

    # Automatically update when the note is edited
    updated_at = models.DateTimeField(auto_now=True)

    # Boolean field to mark if the note is pinned to the top
    pinned = models.BooleanField(default=False)

    # Boolean field to track if the note or task is completed/done
    is_done = models.BooleanField(default=False)

    # Foreign key to link the note to a specific user
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # Optional field for tagging notes to aid in search/filtering
    tags = models.ManyToManyField('Tag', blank=True)

    # Integer field for manual sorting order (optional feature)
    order = models.IntegerField(default=0)

    # String representation of the note
    def __str__(self):
        return self.title

class Tag(models.Model):
    # Tag name for categorizing notes
    name = models.CharField(max_length=50)

    # String representation of the tag
    def __str__(self):
        return self.name


class ExpenseRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(null=True)
    fuel = models.FloatField(default=0)
    plates = models.FloatField(default=0)
    wsib = models.FloatField(default=0)
    repairs = models.FloatField(default=0)
    parking = models.FloatField(default=0)
    wash = models.FloatField(default=0)
    def_fluid = models.FloatField(default=0)
    insurance = models.FloatField(default=0)
    total = models.FloatField(editable=False, default=0)
    tax_paid = models.FloatField(editable=False, default=0)

    def save(self, *args, **kwargs):
        total_dec = sum(
            (
                ensure_decimal(self.fuel),
                ensure_decimal(self.plates),
                ensure_decimal(self.wsib),
                ensure_decimal(self.repairs),
                ensure_decimal(self.parking),
                ensure_decimal(self.wash),
                ensure_decimal(self.def_fluid),
                ensure_decimal(self.insurance),
            ),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.total = float(total_dec)
        user_profile = self.user.profile
        self.tax_paid = float(calculate_tax_total(total_dec, user_profile.province))
        super().save(*args, **kwargs)

    def __str__(self):
        formatted_date = self.date.strftime('%B %d') if self.date else 'No Date'
        return f'{formatted_date} - total expense {self.total}'

    class Meta:
        verbose_name = "Expense Record"
        verbose_name_plural = "Expense Records"

FREQUENCY_CHOICES = [
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('biweekly', 'Bi-Weekly'),
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('yearly', 'Yearly'),
]

class MechExpense(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    vendor = models.CharField(max_length=50)
    date = models.DateField(null=True)
    receipt_no = models.CharField(max_length=20, unique=True, null=True, blank=True)
    categorie = models.CharField(max_length=50, null=True)
    unit_number = models.CharField(max_length=50, null=True, blank=True)
    odometer_reading = models.IntegerField(null=True, blank=True)  # For "Fuel"
    paid = models.BooleanField(default=False)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    tax_included = models.BooleanField(default=False)
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES, null=True, blank=True)
    custom_tax_rate = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    record_in_inventory = models.BooleanField(
        default=True,
        help_text="When enabled, expense items update inventory stock levels.",
    )

    # Fields for recurring payments
    is_recurring = models.BooleanField(default=False)
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, null=True, blank=True)
    next_occurrence = models.DateField(null=True, blank=True)

    def __str__(self):
        return f'{self.date} - {self.vendor}'

    def calculate_totals(self):
        expenses = self.mechexpenseitem_set.all()
        total_amount = sum(
            (ensure_decimal(expense.amount) for expense in expenses),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        province_code = self._get_effective_province_code()
        custom_rate = self.custom_tax_rate if province_code == 'CU' else None

        if self.tax_included:
            _, total_tax, total_amount_excl_tax = calculate_tax_components(
                total_amount,
                province_code,
                tax_included=True,
                custom_tax_rate=custom_rate,
            )
            total_amount_incl_tax = total_amount  # Since tax is included
        else:
            total_amount_excl_tax = total_amount
            _, total_tax, _ = calculate_tax_components(
                total_amount,
                province_code,
                tax_included=False,
                custom_tax_rate=custom_rate,
            )
            total_amount_incl_tax = (total_amount + total_tax).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )

        return total_amount_incl_tax, total_tax, total_amount_excl_tax

    def _get_effective_province_code(self):
        profile_province = getattr(getattr(self.user, "profile", None), "province", None)
        return self.province or profile_province

    def get_tax_rate_info(self):
        province_code = self._get_effective_province_code()
        if not province_code:
            return 0.0, "Tax rate not set"

        if province_code == 'CU' and self.custom_tax_rate is not None:
            rate_decimal = Decimal(str(self.custom_tax_rate))
            percent_display = self._format_percentage_value(rate_decimal)
            return float(rate_decimal), f"Custom ({percent_display}%)"

        rate_value = PROVINCE_TAX_RATES.get(province_code, 0)
        rate_decimal = Decimal(str(rate_value))
        percent_display = self._format_percentage_value(rate_decimal)
        province_label = PROVINCE_DISPLAY_MAP.get(province_code, province_code)
        return float(rate_decimal), f"{province_label} ({percent_display}%)"

    def get_tax_label(self):
        return self.get_tax_rate_info()[1]

    def _format_percentage_value(self, decimal_rate):
        percent_value = decimal_rate * Decimal('100')
        formatted = format(percent_value.normalize(), 'f')
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted

    @property
    def total_paid_amount(self):
        annotated_total = getattr(self, 'paid_total', None)
        if annotated_total is not None:
            return annotated_total

        paid_total = self.payments.aggregate(total=Sum('amount'))['total']
        return paid_total or Decimal('0.00')

    @property
    def total_credit_amount(self):
        annotated_total = getattr(self, 'credit_total', None)
        if annotated_total is not None:
            return Decimal(str(annotated_total))
        total = Decimal('0.00')
        items = self.supplier_credit_items.select_related('supplier_credit')
        for item in items:
            line_total = ensure_decimal(item.amount)
            if item.supplier_credit and not item.supplier_credit.tax_included:
                line_total += ensure_decimal(item.tax_paid)
            total += line_total
        return total

    @property
    def remaining_balance(self):
        total_amount_incl_tax, _, _ = self.calculate_totals()
        total_amount_incl_tax = Decimal(str(total_amount_incl_tax or 0))
        remaining = total_amount_incl_tax - self.total_paid_amount - self.total_credit_amount
        return remaining if remaining > 0 else Decimal('0.00')

    @property
    def payment_status(self):
        if self.remaining_balance <= 0:
            return 'paid'
        if self.total_paid_amount > 0 or self.total_credit_amount > 0:
            return 'partial'
        return 'unpaid'

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            self.receipt_no = self.generate_unique_receipt_no()
        super(MechExpense, self).save(*args, **kwargs)

    def generate_unique_receipt_no(self):
        """
        Generates a unique receipt number.
        This example uses UUIDs, but you can customize this method to fit your receipt numbering scheme.
        """
        while True:
            new_receipt_no = str(uuid.uuid4()).split('-')[0]  # Shorten UUID for brevity
            if not MechExpense.objects.filter(receipt_no=new_receipt_no).exists():
                return new_receipt_no

    class Meta:
        verbose_name = "Receipt"
        verbose_name_plural = "Receipts"


class MechExpensePayment(models.Model):
    mech_expense = models.ForeignKey(MechExpense, on_delete=models.CASCADE, related_name='payments')
    cheque = models.ForeignKey(
        'SupplierCheque',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expense_payments',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=50)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_expense_payments',
    )

    def __str__(self):
        return f"{self.mech_expense.vendor} - {self.amount} via {self.method}"

    class Meta:
        verbose_name = "Expense Payment"
        verbose_name_plural = "Expense Payments"

class MechExpenseItem(models.Model):
    mech_expense = models.ForeignKey(MechExpense, on_delete=models.CASCADE)
    part_no = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True)
    qty = models.FloatField(default=1)
    price = models.FloatField(default=0)
    amount = models.FloatField(editable=False, default=0)
    tax_paid = models.FloatField(editable=False, default=0)

    def save(self, *args, **kwargs):
        qty_dec = ensure_decimal(self.qty)
        price_dec = ensure_decimal(self.price)
        amount_dec = (qty_dec * price_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.amount = float(amount_dec)
        mech_expense = self.mech_expense

        # Determine the province to use when calculating tax
        province = mech_expense.province
        if not province:
            province = getattr(getattr(mech_expense.user, "profile", None), "province", None)
        custom_rate = mech_expense.custom_tax_rate if province == 'CU' else None
        _, tax_total, _ = calculate_tax_components(
            amount_dec,
            province,
            tax_included=mech_expense.tax_included,
            custom_tax_rate=custom_rate,
        )
        self.tax_paid = float(tax_total)
        super().save(*args, **kwargs)


    def __str__(self):
        return f'{self.mech_expense.vendor} - {self.description} - {self.amount}'

    class Meta:
        verbose_name = "Expense Item"
        verbose_name_plural = "Expense Items"

class SupplierCredit(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    supplier = models.ForeignKey(
        'Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='credits',
    )
    supplier_name = models.CharField(max_length=150, blank=True)
    credit_no = models.CharField(max_length=20, unique=True, null=True, blank=True)
    date = models.DateField(null=True)
    memo = models.TextField(null=True, blank=True)
    tax_included = models.BooleanField(default=False)
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES, null=True, blank=True)
    custom_tax_rate = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    record_in_inventory = models.BooleanField(
        default=True,
        help_text="When enabled, credit items adjust inventory stock levels.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        credit_label = self.credit_no or f"Credit {self.pk}"
        supplier_label = self.supplier_name or (self.supplier.name if self.supplier else '')
        return f"{credit_label} - {supplier_label}".strip()

    def save(self, *args, **kwargs):
        if self.supplier:
            self.supplier_name = self.supplier.name
        if not self.credit_no:
            self.credit_no = self.generate_unique_credit_no()
        super().save(*args, **kwargs)

    def generate_unique_credit_no(self):
        while True:
            new_credit_no = str(uuid.uuid4()).split('-')[0]
            if not SupplierCredit.objects.filter(credit_no=new_credit_no).exists():
                return new_credit_no

    def _get_effective_province_code(self):
        profile_province = getattr(getattr(self.user, "profile", None), "province", None)
        return self.province or profile_province

    def calculate_totals(self):
        items = self.items.all()
        total_amount = sum(
            (ensure_decimal(item.amount) for item in items),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        province_code = self._get_effective_province_code()
        custom_rate = self.custom_tax_rate if province_code == 'CU' else None

        if self.tax_included:
            _, total_tax, total_amount_excl_tax = calculate_tax_components(
                total_amount,
                province_code,
                tax_included=True,
                custom_tax_rate=custom_rate,
            )
            total_amount_incl_tax = total_amount
        else:
            total_amount_excl_tax = total_amount
            _, total_tax, _ = calculate_tax_components(
                total_amount,
                province_code,
                tax_included=False,
                custom_tax_rate=custom_rate,
            )
            total_amount_incl_tax = (total_amount + total_tax).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )

        return total_amount_incl_tax, total_tax, total_amount_excl_tax

    def _format_percentage_value(self, decimal_rate):
        percent_value = decimal_rate * Decimal('100')
        formatted = format(percent_value.normalize(), 'f')
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted

    def get_tax_rate_info(self):
        province_code = self._get_effective_province_code()
        if not province_code:
            return 0.0, "Tax rate not set"

        if province_code == 'CU' and self.custom_tax_rate is not None:
            rate_decimal = Decimal(str(self.custom_tax_rate))
            percent_display = self._format_percentage_value(rate_decimal)
            return float(rate_decimal), f"Custom ({percent_display}%)"

        rate_value = PROVINCE_TAX_RATES.get(province_code, 0)
        rate_decimal = Decimal(str(rate_value))
        percent_display = self._format_percentage_value(rate_decimal)
        province_label = PROVINCE_DISPLAY_MAP.get(province_code, province_code)
        return float(rate_decimal), f"{province_label} ({percent_display}%)"

    def get_tax_label(self):
        return self.get_tax_rate_info()[1]

    @property
    def applied_amount(self):
        total = Decimal('0.00')
        for item in self.items.all():
            if not item.source_expense_id:
                continue
            line_total = ensure_decimal(item.amount)
            if not self.tax_included:
                line_total += ensure_decimal(item.tax_paid)
            total += line_total
        return total

    @property
    def available_amount(self):
        total_amount_incl_tax, _, _ = self.calculate_totals()
        total_amount_incl_tax = Decimal(str(total_amount_incl_tax or 0))
        remaining = total_amount_incl_tax - self.applied_amount
        return remaining if remaining > 0 else Decimal('0.00')


class SupplierCreditItem(models.Model):
    supplier_credit = models.ForeignKey(SupplierCredit, on_delete=models.CASCADE, related_name='items')
    source_expense = models.ForeignKey(
        'MechExpense',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_credit_items',
    )
    source_expense_item = models.ForeignKey(
        'MechExpenseItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_credit_items',
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_credit_items',
    )
    part_no = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    qty = models.FloatField(default=1)
    price = models.FloatField(default=0)
    amount = models.FloatField(editable=False, default=0)
    tax_paid = models.FloatField(editable=False, default=0)

    def save(self, *args, **kwargs):
        qty_dec = ensure_decimal(self.qty)
        price_dec = ensure_decimal(self.price)
        amount_dec = (qty_dec * price_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.amount = float(amount_dec)
        credit = self.supplier_credit

        province = credit.province or getattr(getattr(credit.user, "profile", None), "province", None)
        custom_rate = credit.custom_tax_rate if province == 'CU' else None
        _, tax_total, _ = calculate_tax_components(
            amount_dec,
            province,
            tax_included=credit.tax_included,
            custom_tax_rate=custom_rate,
        )
        self.tax_paid = float(tax_total)
        super().save(*args, **kwargs)

    def __str__(self):
        credit_label = self.supplier_credit.credit_no if self.supplier_credit else 'Credit'
        return f'{credit_label} - {self.description or self.part_no or "Item"} - {self.amount}'

    class Meta:
        verbose_name = "Supplier Credit Item"
        verbose_name_plural = "Supplier Credit Items"


class CustomerCredit(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='credits',
    )
    customer_name = models.CharField(max_length=150, blank=True)
    credit_no = models.CharField(max_length=20, unique=True, null=True, blank=True)
    date = models.DateField(null=True)
    memo = models.TextField(null=True, blank=True)
    tax_included = models.BooleanField(default=False)
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES, null=True, blank=True)
    custom_tax_rate = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    record_in_inventory = models.BooleanField(
        default=True,
        help_text="When enabled, credit items adjust inventory stock levels.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        credit_label = self.credit_no or f"Credit {self.pk}"
        customer_label = self.customer_name or (self.customer.name if self.customer else '')
        return f"{credit_label} - {customer_label}".strip()

    def save(self, *args, **kwargs):
        if self.customer:
            self.customer_name = self.customer.name
        if not self.credit_no:
            self.credit_no = self.generate_unique_credit_no()
        super().save(*args, **kwargs)

    def generate_unique_credit_no(self):
        while True:
            new_credit_no = str(uuid.uuid4()).split('-')[0]
            if not CustomerCredit.objects.filter(credit_no=new_credit_no).exists():
                return new_credit_no

    def _get_effective_province_code(self):
        profile_province = getattr(getattr(self.user, "profile", None), "province", None)
        return self.province or profile_province

    def calculate_totals(self):
        items = self.items.all()
        total_amount = sum(
            (ensure_decimal(item.amount) for item in items),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        province_code = self._get_effective_province_code()
        custom_rate = self.custom_tax_rate if province_code == 'CU' else None

        if self.tax_included:
            _, total_tax, total_amount_excl_tax = calculate_tax_components(
                total_amount,
                province_code,
                tax_included=True,
                custom_tax_rate=custom_rate,
            )
            total_amount_incl_tax = total_amount
        else:
            total_amount_excl_tax = total_amount
            _, total_tax, _ = calculate_tax_components(
                total_amount,
                province_code,
                tax_included=False,
                custom_tax_rate=custom_rate,
            )
            total_amount_incl_tax = (total_amount + total_tax).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )

        return total_amount_incl_tax, total_tax, total_amount_excl_tax

    def _format_percentage_value(self, decimal_rate):
        percent_value = decimal_rate * Decimal('100')
        formatted = format(percent_value.normalize(), 'f')
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted

    def get_tax_rate_info(self):
        province_code = self._get_effective_province_code()
        if not province_code:
            return 0.0, "Tax rate not set"

        if province_code == 'CU' and self.custom_tax_rate is not None:
            rate_decimal = Decimal(str(self.custom_tax_rate))
            percent_display = self._format_percentage_value(rate_decimal)
            return float(rate_decimal), f"Custom ({percent_display}%)"

        rate_value = PROVINCE_TAX_RATES.get(province_code, 0)
        rate_decimal = Decimal(str(rate_value))
        percent_display = self._format_percentage_value(rate_decimal)
        province_label = PROVINCE_DISPLAY_MAP.get(province_code, province_code)
        return float(rate_decimal), f"{province_label} ({percent_display}%)"

    def get_tax_label(self):
        return self.get_tax_rate_info()[1]

    @property
    def applied_amount(self):
        total = Decimal('0.00')
        for item in self.items.all():
            if not item.source_invoice_id:
                continue
            line_total = ensure_decimal(item.amount)
            if not self.tax_included:
                line_total += ensure_decimal(item.tax_paid)
            total += line_total
        return total

    @property
    def available_amount(self):
        total_amount_incl_tax, _, _ = self.calculate_totals()
        total_amount_incl_tax = Decimal(str(total_amount_incl_tax or 0))
        remaining = total_amount_incl_tax - self.applied_amount
        return remaining if remaining > 0 else Decimal('0.00')

    def _find_inventory_product(self, item):
        if item.product:
            return item.product

        part = (item.part_no or "").strip()
        desc = (item.description or "").strip()

        if not part and not desc:
            return None

        qs = Product.objects.filter(user=self.user)
        product = None
        if part:
            product = qs.filter(Q(sku__iexact=part) | Q(name__iexact=part)).first()
        if not product and desc:
            product = qs.filter(name__iexact=desc).first()

        return product

    def _log_inventory_transactions(self, items, transaction_type, remark_suffix):
        for item in items:
            product = self._find_inventory_product(item)
            if not product:
                continue
            qty_decimal = Decimal(str(item.qty or 0)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            qty_int = int(qty_decimal) if qty_decimal > 0 else 0
            if qty_int <= 0:
                continue
            remarks = f"Customer credit {self.credit_no or self.pk} - {remark_suffix}"
            InventoryTransaction.objects.create(
                product=product,
                transaction_type=transaction_type,
                quantity=qty_int,
                remarks=remarks,
                user=self.user,
            )

    def delete(self, using=None, keep_parents=False):
        if self.record_in_inventory:
            items = list(self.items.select_related('product'))
            try:
                self._log_inventory_transactions(items, 'OUT', 'credit deleted')
            except Exception:
                logger.warning(
                    "Inventory sync on delete failed for customer credit %s",
                    getattr(self, "id", None),
                )
        return super().delete(using=using, keep_parents=keep_parents)


class CustomerCreditItem(models.Model):
    customer_credit = models.ForeignKey(CustomerCredit, on_delete=models.CASCADE, related_name='items')
    source_invoice = models.ForeignKey(
        'GroupedInvoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_credit_items',
    )
    source_invoice_item = models.ForeignKey(
        'IncomeRecord2',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_credit_items',
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_credit_items',
    )
    part_no = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    qty = models.FloatField(default=1)
    price = models.FloatField(default=0)
    amount = models.FloatField(editable=False, default=0)
    tax_paid = models.FloatField(editable=False, default=0)

    def save(self, *args, **kwargs):
        qty_dec = ensure_decimal(self.qty)
        price_dec = ensure_decimal(self.price)
        amount_dec = (qty_dec * price_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.amount = float(amount_dec)
        credit = self.customer_credit

        province = credit.province or getattr(getattr(credit.user, "profile", None), "province", None)
        custom_rate = credit.custom_tax_rate if province == 'CU' else None
        _, tax_total, _ = calculate_tax_components(
            amount_dec,
            province,
            tax_included=credit.tax_included,
            custom_tax_rate=custom_rate,
        )
        self.tax_paid = float(tax_total)
        super().save(*args, **kwargs)

    def __str__(self):
        credit_label = self.customer_credit.credit_no if self.customer_credit else 'Credit'
        return f'{credit_label} - {self.description or self.part_no or "Item"} - {self.amount}'

    class Meta:
        verbose_name = "Customer Credit Item"
        verbose_name_plural = "Customer Credit Items"


class SupplierCheque(models.Model):
    STATUS_CHOICES = [
        ('issued', 'Issued'),
        ('void', 'Void'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    supplier = models.ForeignKey(
        'Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cheques',
    )
    supplier_name = models.CharField(max_length=150, blank=True)
    cheque_number = models.CharField(max_length=30)
    bank_account = models.CharField(max_length=120, blank=True)
    date = models.DateField(default=timezone.localdate)
    memo = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='issued')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        supplier_label = self.supplier_name or (self.supplier.name if self.supplier else '')
        return f"Cheque {self.cheque_number} - {supplier_label}".strip()

    def save(self, *args, **kwargs):
        if self.supplier:
            self.supplier_name = self.supplier.name
        super().save(*args, **kwargs)

    @property
    def total_amount(self):
        total = self.lines.aggregate(total=Sum('amount'))['total']
        return total or Decimal('0.00')


class SupplierChequeLine(models.Model):
    cheque = models.ForeignKey(SupplierCheque, on_delete=models.CASCADE, related_name='lines')
    mech_expense = models.ForeignKey(
        MechExpense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cheque_lines',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    memo = models.TextField(null=True, blank=True)

    def __str__(self):
        expense_label = self.mech_expense.receipt_no if self.mech_expense else 'Expense'
        return f"{self.cheque.cheque_number} - {expense_label} - {self.amount}"

class BusinessBankAccount(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="business_bank_accounts",
    )
    name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Business Bank Account"
        verbose_name_plural = "Business Bank Accounts"
        ordering = ["name", "id"]
        unique_together = ("user", "name", "account_number")

    @property
    def display_label(self):
        if self.account_number:
            return f"{self.name} ({self.account_number})"
        return self.name

    def __str__(self):
        return self.display_label

class IncomeRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(null=True)
    ticket = models.FloatField(default=0, blank=True)
    jobsite = models.FloatField(null=True)
    truck = models.FloatField(default=3335)
    job = models.CharField(max_length=20, blank=True)
    qty = models.FloatField(default=0)
    rate = models.FloatField(default=0)
    amount = models.FloatField(editable=False, default=0)
    tax_collected = models.FloatField(editable=False, default=0)

    def save(self, *args, **kwargs):
        qty_dec = ensure_decimal(self.qty)
        rate_dec = ensure_decimal(self.rate)
        amount_dec = (qty_dec * rate_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.amount = float(amount_dec)
        user_profile = self.user.profile
        self.tax_collected = float(calculate_tax_total(amount_dec, user_profile.province))
        super().save(*args, **kwargs)

    def __str__(self):
        formatted_date = self.date.strftime('%B %d') if self.date else 'No Date'
        return f'{formatted_date} - total income {self.amount}'

    class Meta:
        verbose_name = "Income Record"
        verbose_name_plural = "Income Records"

class InvoiceDetail(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bill_to = models.TextField(help_text="Enter the full billing address")

    def __str__(self):
        return self.bill_to

    class Meta:
        verbose_name = "Invoice Detail"
        verbose_name_plural = "Invoice Details"

class Customer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)  # Associates the customer with a user
    portal_user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="customer_portal",
        help_text="Login account for this customer",
    )
    PORTAL_STATUS_PENDING = "pending"
    PORTAL_STATUS_APPROVED = "approved"
    PORTAL_STATUS_CHOICES = [
        (PORTAL_STATUS_PENDING, "Pending approval"),
        (PORTAL_STATUS_APPROVED, "Approved"),
    ]
    portal_signup_status = models.CharField(
        max_length=20,
        choices=PORTAL_STATUS_CHOICES,
        default=PORTAL_STATUS_APPROVED,
        help_text="Controls whether customer portal access is pending approval.",
    )
    name = models.CharField(max_length=100)  # Equivalent to bill_to
    email = models.EmailField(null=True, blank=True)
    cc_emails = models.TextField(
        null=True,
        blank=True,
        help_text="Additional CC email addresses, separated by commas.",
    )
    address = models.TextField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    gst_hst_number = models.CharField(max_length=20, null=True, blank=True)  # Optional tax number
    next_followup = models.DateField(null=True, blank=True)
    collection_notes = models.TextField(null=True, blank=True)


    # New field for GST/HST collection
    collect_gst_hst = models.BooleanField(
        default=False,
        verbose_name="Do you collect GST/HST from this customer?"
    )
    quickbooks_customer_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Identifier for the matching customer in QuickBooks.",
    )
    charge_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Charge rate (per hour)"
    )

    vehicle_count = models.PositiveIntegerField(
        default=0,
        editable=False, # This count will be managed by the system
        verbose_name="Number of Unique Vehicles"
    )

    @staticmethod
    def parse_cc_emails(value):
        if not value:
            return []
        raw_emails = re.split(r"[,\n;]+", str(value))
        cleaned = []
        seen = set()
        for entry in raw_emails:
            email = entry.strip()
            if not email:
                continue
            try:
                validate_email(email)
            except ValidationError:
                continue
            key = email.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(email)
        return cleaned

    def get_cc_emails(self):
        return self.parse_cc_emails(self.cc_emails)

    def __str__(self):
        return self.name

    def update_vehicle_count(self):
        """
        Recalculates and updates the vehicle_count based on associated Vehicle records.
        Saves the customer instance if the count has changed.
        """
        # The related_name 'vehicles' will be defined in the Vehicle model's ForeignKey
        count = self.vehicles.count()
        if self.vehicle_count != count:
            self.vehicle_count = count
            self.save(update_fields=['vehicle_count'])
        return count

    class Meta:
        unique_together = (
            ("user", "quickbooks_customer_id"),
        )


class StorefrontCartItem(models.Model):
    """Persisted cart items for customer portal storefront users."""
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="storefront_cart_items",
    )
    store_owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="storefront_cart_items",
        help_text="Storefront location the item was added from.",
    )
    product = models.ForeignKey(
        "Product",
        on_delete=models.CASCADE,
        related_name="storefront_cart_items",
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("customer", "store_owner", "product")

    def __str__(self):
        return f"{self.customer} - {self.product} ({self.quantity})"


class TaxExemptionReason(models.Model):
    """Stores user specific tax exemption reasons for quick reuse."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tax_exemption_reasons")
    reason = models.CharField(max_length=255)

    class Meta:
        unique_together = ("user", "reason")

    def __str__(self):
        return self.reason


class Driver(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    gst_hst_number = models.CharField(max_length=50, blank=True, null=True)
    license_number = models.CharField(max_length=50, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    pay_gst_hst = models.BooleanField(default=False)  # whether you pay GST/HST to this driver
    pay_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Pay rate (per hour)"
    )
    extra_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Extra hours"
    )

    def __str__(self):
        return self.name

class GroupedInvoice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    stripe_invoice_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="The Stripe Invoice ID so we can fetch invoice_pdf"
    )
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, related_name='invoices')
    po_number = models.CharField(max_length=20, null=True, blank=True)
    date = models.DateField(null=True)
    date_fully_paid = models.DateField(null=True, blank=True)
    date_from = models.DateField(null=True)
    date_to = models.DateField(null=True)
    bill_to = models.CharField(max_length=50, null=True)
    bill_to_address = models.TextField(null=True, blank=True)
    bill_to_email = models.EmailField(null=True)
    vin_no = models.CharField(max_length=17, null=True)
    mileage = models.FloatField(null=True)
    unit_no = models.CharField(max_length=64, null=True)
    make_model = models.CharField(max_length=25, null=True)
    license_plate = models.CharField(max_length=20, null=True, blank=True)
    # NOTE: invoice numbers must be unique per business (user), not globally.
    # Global uniqueness prevents importing/operating multiple businesses that use the same numbering scheme.
    invoice_number = models.CharField(max_length=20, blank=True, null=True, editable=False)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    stripe_payment_link = models.URLField(max_length=500, null=True, blank=True)
    stripe_subscription_link = models.URLField(max_length=500, null=True, blank=True)
    clover_order_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Clover order ID used for online/pos payments.",
    )
    clover_payment_link = models.URLField(max_length=500, null=True, blank=True)
    quickbooks_invoice_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Identifier for the matching invoice in QuickBooks.",
    )
    quickbooks_sync_token = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="QuickBooks sync token used for optimistic locking.",
    )
    quickbooks_last_sync_at = models.DateTimeField(blank=True, null=True)
    quickbooks_needs_sync = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_subscription = models.BooleanField(
        default=False,
        help_text="Create a recurring subscription instead of a one-time payment",
    )
    subscription_frequency = models.CharField(
        max_length=10,
        choices=FREQUENCY_CHOICES,
        null=True,
        blank=True,
    )
    tax_exempt = models.BooleanField(default=False)
    tax_exempt_reason = models.CharField(max_length=255, null=True, blank=True)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, blank=True, null=True)
    notes = models.TextField(null=True, blank=True)


    def recalculate_total_amount(self):
        # Use Django's Sum aggregation for efficiency and Decimal handling
        from django.db.models import Sum, F, DecimalField # Ensure DecimalField is imported here or globally
        from django.db.models.functions import Coalesce # Import Coalesce

        # Aggregate directly from the related IncomeRecord2 instances
        # Coalesce ensures we get Decimal('0.00') if there are no records, instead of None
        totals = self.income_records.aggregate(
            total_job_amount=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField()),
            total_tax=Coalesce(Sum('tax_collected'), Decimal('0.00'), output_field=DecimalField())
        )

        total_job_amount = totals['total_job_amount'] or Decimal('0.00')
        total_tax = totals['total_tax'] or Decimal('0.00')

        if not isinstance(total_job_amount, Decimal):
            total_job_amount = Decimal(str(total_job_amount))
        if not isinstance(total_tax, Decimal):
            total_tax = Decimal(str(total_tax))

        # Sum the Decimal results and ensure correct rounding
        self.total_amount = (total_job_amount + total_tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        # Save only the updated field
        self.save(update_fields=['total_amount'])

    def ensure_inventory_transactions(self):
        """
        Guarantee that stock-out transactions exist for every product used on this invoice.
        This backfills any missing inventory postings (e.g., if lines were created in bulk
        without hitting IncomeRecord2.save) while avoiding duplicate deductions.
        """
        invoice_label = self.invoice_number or f"Invoice {self.pk}"
        expected_by_product = {}

        for item in self.income_records.all():
            if not item.product_id or item.qty is None or item.qty <= 0:
                continue
            if getattr(item.product, 'item_type', 'inventory') != 'inventory':
                continue
            qty_int = int(Decimal(str(item.qty)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if qty_int <= 0:
                continue
            expected_by_product[item.product_id] = expected_by_product.get(item.product_id, 0) + qty_int

        if not expected_by_product:
            return

        remarks = f"Sold with invoice {invoice_label}"
        existing = (
            InventoryTransaction.objects.filter(
                product_id__in=expected_by_product.keys(),
                transaction_type="OUT",
                remarks=remarks,
            )
            .filter(
                Q(user=self.user) | Q(user__isnull=True, product__user=self.user)
            )
            .values("product_id")
            .annotate(total_qty=Sum("quantity"))
        )
        posted = {row["product_id"]: int(row.get("total_qty") or 0) for row in existing}

        for product_id, expected_qty in expected_by_product.items():
            missing_qty = expected_qty - posted.get(product_id, 0)
            if missing_qty <= 0:
                continue

            owner_user = self.user
            try:
                product_obj = Product.objects.select_related("user").get(pk=product_id)
                if owner_user is None:
                    owner_user = product_obj.user
            except Product.DoesNotExist:
                product_obj = None
                owner_user = self.user

            # Auto-top-up inventory to avoid insufficient stock errors when posting OUT.
            if product_obj:
                stock_owner = _resolve_stock_owner(owner_user, product_obj)
                stock_record, _ = ProductStock.objects.get_or_create(
                    product=product_obj,
                    user=stock_owner,
                    defaults={"quantity_in_stock": 0, "reorder_level": 0},
                )
                current_stock = stock_record.quantity_in_stock or 0
                if current_stock < missing_qty:
                    replenish_qty = missing_qty - current_stock
                    InventoryTransaction.objects.create(
                        product_id=product_id,
                        transaction_type="IN",
                        quantity=replenish_qty,
                        transaction_date=timezone.now(),
                        remarks=f"Auto restock for {invoice_label}",
                        user=owner_user,
                    )

            InventoryTransaction.objects.create(
                product_id=product_id,
                transaction_type="OUT",
                quantity=missing_qty,
                transaction_date=timezone.now(),
                remarks=remarks,
                user=owner_user,
            )


    def total_paid(self):
        total = self.payments.aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0.00')
        return total

    @property
    def total_credit_amount(self):
        annotated_total = getattr(self, 'credit_total', None)
        if annotated_total is not None:
            return Decimal(str(annotated_total))
        total = Decimal('0.00')
        items = self.customer_credit_items.select_related('customer_credit')
        for item in items:
            line_total = ensure_decimal(item.amount)
            if item.customer_credit and not item.customer_credit.tax_included:
                line_total += ensure_decimal(item.tax_paid)
            total += line_total
        return total

    def balance_due(self):
        total_amount = self.total_amount or Decimal('0.00')
        return total_amount - self.total_paid() - self.total_credit_amount

    @property
    def payment_status(self):
        total_paid = self.total_paid()
        total_amount = self.total_amount or Decimal('0.00')

        # Round values to 2 decimal places
        total_paid = total_paid.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_amount = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Define a tolerance
        tolerance = Decimal('0.01')

        if total_paid <= Decimal('0.00') + tolerance:
            return 'Unpaid'
        elif total_paid + tolerance < total_amount:
            return 'Partially Paid'
        else:
            return 'Paid'

    def get_payment_link_provider(self):
        profile = getattr(self.user, "profile", None)
        provider = getattr(profile, "payment_link_provider", PAYMENT_LINK_PROVIDER_STRIPE)
        if provider not in {
            PAYMENT_LINK_PROVIDER_STRIPE,
            PAYMENT_LINK_PROVIDER_CLOVER,
            PAYMENT_LINK_PROVIDER_NONE,
        }:
            return PAYMENT_LINK_PROVIDER_STRIPE
        return provider

    @property
    def payment_link(self):
        provider = self.get_payment_link_provider()
        if provider == PAYMENT_LINK_PROVIDER_CLOVER:
            return self.clover_payment_link
        if provider == PAYMENT_LINK_PROVIDER_NONE:
            return None
        if self.is_subscription:
            return self.stripe_subscription_link
        return self.stripe_payment_link

    def update_date_fully_paid(self):
        total_amount = self.total_amount or Decimal('0.00')
        total_paid = self.total_paid().quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_amount = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        tolerance = Decimal('0.01')

        if total_paid + tolerance >= total_amount and not self.date_fully_paid:
            last_payment = self.payments.order_by('-date').first()
            if last_payment:
                self.date_fully_paid = last_payment.date
                self.save(update_fields=['date_fully_paid'])
        elif total_paid + tolerance < total_amount and self.date_fully_paid:
            # If payments are deleted or adjusted, reset date_fully_paid
            self.date_fully_paid = None
            self.save(update_fields=['date_fully_paid'])

    @property
    def due_date(self):
        """
        Calculate the due date by adding the term (in days) from the user's profile to the invoice date.
        If the profile term isn't found, default to 30 days.
        """
        # Get the number of days for the term from the user's profile
        # (Assumes that the Profile model has a 'term' field matching keys in TERM_CHOICES.)
        days = TERM_CHOICES.get(self.user.profile.term, 30)
        if self.date:
            return self.date + timedelta(days=days)
        # If date is not set, return None (or you can return self.date or a default date)
        return None

    @staticmethod
    def _format_invoice_number(user, sequence_number):
        return f'INV-{user.id}-{sequence_number:04d}'

    @staticmethod
    def generate_invoice_number(user, *, commit=True):
        with transaction.atomic():
            profile = Profile.objects.select_for_update().filter(user=user).first()
            sequence_override = None
            if profile and profile.invoice_sequence_next:
                sequence_override = int(profile.invoice_sequence_next)

            if sequence_override:
                new_number = max(sequence_override, 1)
            else:
                last_invoice = (
                    GroupedInvoice.objects
                    .select_for_update()
                    .filter(user=user)
                    .order_by('-id')
                    .first()
                )
                if last_invoice and last_invoice.invoice_number:
                    try:
                        last_number = int(last_invoice.invoice_number.split('-')[-1])
                        new_number = last_number + 1
                    except ValueError:
                        new_number = 150  # Start from 0150 if the last number parsing fails
                else:
                    new_number = 150  # Start from 0150 if there is no previous invoice

            candidate = new_number
            invoice_number = GroupedInvoice._format_invoice_number(user, candidate)
            while GroupedInvoice.objects.filter(user=user, invoice_number=invoice_number).exists():
                candidate += 1
                invoice_number = GroupedInvoice._format_invoice_number(user, candidate)

            if commit and profile and sequence_override:
                profile.invoice_sequence_next = candidate + 1
                profile.save(update_fields=['invoice_sequence_next'])

            return invoice_number

    def save(self, *args, **kwargs):
        # Check if it's a new invoice or an update
        is_new = not self.pk
        old_total_amount = None

        if not is_new:
            old_invoice = GroupedInvoice.objects.filter(pk=self.pk).first()
            if old_invoice:
                old_total_amount = old_invoice.total_amount

        # Determine whether to flag the invoice for QuickBooks synchronization.
        quickbooks_only_fields = {
            'quickbooks_invoice_id',
            'quickbooks_sync_token',
            'quickbooks_last_sync_at',
            'quickbooks_needs_sync',
        }
        update_fields = kwargs.get('update_fields')
        update_fields_list = list(update_fields) if update_fields else []
        skip_quickbooks_flag = getattr(self, '_skip_quickbooks_sync_flag', False)
        mark_for_quickbooks_sync = False

        if skip_quickbooks_flag:
            kwargs = dict(kwargs)
            self._skip_quickbooks_sync_flag = False
        else:
            if not update_fields or not set(update_fields_list).issubset(quickbooks_only_fields):
                mark_for_quickbooks_sync = True

        # Also check if we are only updating the stripe-related links to avoid loops
        # (i.e. create_payment_link or create_subscription_link call self.save(update_fields=[...]))
        only_updating_link = any(
            field in update_fields_list
            for field in (
                'stripe_payment_link',
                'stripe_subscription_link',
                'clover_payment_link',
                'clover_order_id',
            )
        )

        # First, generate invoice_number if new and missing
        if is_new and not self.invoice_number:
            self.invoice_number = self.generate_invoice_number(self.user)

        super().save(*args, **kwargs)

        if mark_for_quickbooks_sync:
            GroupedInvoice.objects.filter(pk=self.pk).update(quickbooks_needs_sync=True)

        # After saving, decide if we need to create/update the payment or subscription link
        if not only_updating_link:
            current_link = self.payment_link
            if is_new or (old_total_amount != self.total_amount) or not current_link:
                if self.is_subscription:
                    self.create_subscription_link()
                else:
                    self.create_online_payment_link()

    def create_online_payment_link(self):
        provider = self.get_payment_link_provider()
        if provider == PAYMENT_LINK_PROVIDER_CLOVER:
            return self.create_clover_payment_link()
        if provider == PAYMENT_LINK_PROVIDER_NONE:
            return None
        return self.create_payment_link()

    def create_clover_payment_link(self):
        """
        Create or update a Clover payment link for this invoice.
        """
        try:
            from .clover_service import CloverClient
            clover_conn = CloverConnection.objects.filter(user=self.user).first()

            if not clover_conn or not clover_conn.is_configured:
                logger.error(
                    "User %s does not have a configured Clover connection.",
                    self.user.username,
                )
                self.clover_payment_link = None
                self.save(update_fields=['clover_payment_link'])
                return

            amount_cents = int(self.total_amount * 100)
            minimum_cents = 50  # 0.50 CAD fallback
            if amount_cents < minimum_cents:
                logger.warning(
                    "Invoice %s amount too low for Clover: %s CAD.",
                    self.invoice_number,
                    self.total_amount,
                )
                self.clover_payment_link = None
                self.save(update_fields=['clover_payment_link'])
                return

            client = CloverClient(clover_conn)
            order_id = self.clover_order_id or client.create_order_for_invoice(self)
            if not order_id:
                self.clover_payment_link = None
                self.save(update_fields=['clover_payment_link'])
                return

            self.clover_order_id = order_id
            response = client.create_payment_link_for_invoice(self, order_id=order_id)
            payment_link = None
            if isinstance(response, dict):
                payment_link = (
                    response.get("checkoutUrl")
                    or response.get("paymentLink")
                    or response.get("url")
                    or response.get("href")
                )
            elif isinstance(response, str):
                payment_link = response

            self.clover_payment_link = payment_link
            self.save(update_fields=['clover_order_id', 'clover_payment_link'])
        except Exception as exc:
            logger.error(
                "Clover payment link error for invoice %s: %s",
                self.invoice_number,
                exc,
            )
            self.clover_payment_link = None
            self.save(update_fields=['clover_payment_link'])

    def create_payment_link(self):
        """
        Safely create or recreate a Stripe payment link whenever needed.
        If total_amount < 0.50, sets link to None.
        """
        try:
            logger.debug(f"Attempting to create payment link for invoice {self.invoice_number}")
            user_stripe_account = UserStripeAccount.objects.get(user=self.user)
            user_profile = self.user.profile

            if (
                user_stripe_account
                and user_stripe_account.stripe_account_id
                and user_stripe_account.is_verified
            ):
                stripe.api_key = settings.STRIPE_SECRET_KEY
                amount_in_cents = int(self.total_amount * 100)
                minimum_cents = 50  # 0.50 CAD

                if amount_in_cents < minimum_cents:
                    logger.warning(f"Invoice {self.invoice_number} amount too low: {self.total_amount} CAD.")
                    self.stripe_payment_link = None
                    self.save(update_fields=['stripe_payment_link'])
                    return

                business_name = getattr(user_profile, 'company_name', None) or "Unknown Business"
                customer_email = self.bill_to_email if self.bill_to_email else None

                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'cad',
                            'product_data': {'name': f'Invoice {self.invoice_number}'},
                            'unit_amount': amount_in_cents,
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url='https://www.smart-invoices.com/success?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url='https://www.smart-invoices.com/cancel',
                    stripe_account=user_stripe_account.stripe_account_id,
                    metadata={
                        'business_name': business_name,
                        'invoice_id': self.id,
                    },
                    customer_email=customer_email
                )

                self.stripe_payment_link = session.url
                self.save(update_fields=['stripe_payment_link'])
                logger.info(f"Stripe Payment Link for {self.invoice_number}: {self.stripe_payment_link}")
            else:
                logger.error(
                    f"User {self.user.username} does not have a verified connected Stripe account."
                )
                self.stripe_payment_link = None
                self.save(update_fields=['stripe_payment_link'])

        except UserStripeAccount.DoesNotExist:
            logger.error(f"UserStripeAccount does not exist for {self.user.username}.")
            self.stripe_payment_link = None
            self.save(update_fields=['stripe_payment_link'])
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {str(e)}")
            self.stripe_payment_link = None
            self.save(update_fields=['stripe_payment_link'])
        except Exception as e:
            logger.error(f"Unexpected error on invoice {self.invoice_number}: {str(e)}")
            self.stripe_payment_link = None
            self.save(update_fields=['stripe_payment_link'])

    def create_subscription_link(self):
        """Create a Stripe Checkout session for a recurring subscription."""
        try:
            logger.debug(
                f"Attempting to create subscription link for invoice {self.invoice_number}"
            )
            user_stripe_account = UserStripeAccount.objects.get(user=self.user)
            if (
                user_stripe_account
                and user_stripe_account.stripe_account_id
                and user_stripe_account.is_verified
            ):
                stripe.api_key = settings.STRIPE_SECRET_KEY
                amount_in_cents = int(self.total_amount * 100)
                minimum_cents = 50  # 0.50 CAD

                if amount_in_cents < minimum_cents:
                    logger.warning(
                        f"Invoice {self.invoice_number} amount too low for subscription: {self.total_amount} CAD."
                    )
                    self.stripe_subscription_link = None
                    self.save(update_fields=['stripe_subscription_link'])
                    return

                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[
                        {
                            'price_data': {
                                'currency': 'cad',
                                'product_data': {
                                    'name': f'Invoice {self.invoice_number} Subscription'
                                },
                                'unit_amount': amount_in_cents,
                                'recurring': {'interval': 'month'},
                            },
                            'quantity': 1,
                        }
                    ],
                    mode='subscription',
                    success_url='https://www.smart-invoices.com/success?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url='https://www.smart-invoices.com/cancel',
                    stripe_account=user_stripe_account.stripe_account_id,
                    metadata={'invoice_id': self.id},
                )

                self.stripe_subscription_link = session.url
                self.save(update_fields=['stripe_subscription_link'])
                logger.info(
                    f"Stripe Subscription Link for {self.invoice_number}: {self.stripe_subscription_link}"
                )
            else:
                logger.error(
                    f"User {self.user.username} does not have a verified connected Stripe account."
                )
                self.stripe_subscription_link = None
                self.save(update_fields=['stripe_subscription_link'])

        except UserStripeAccount.DoesNotExist:
            logger.error(
                f"UserStripeAccount does not exist for {self.user.username}."
            )
            self.stripe_subscription_link = None
            self.save(update_fields=['stripe_subscription_link'])
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {str(e)}")
            self.stripe_subscription_link = None
            self.save(update_fields=['stripe_subscription_link'])
        except Exception as e:
            logger.error(
                f"Unexpected error on invoice {self.invoice_number}: {str(e)}"
            )
            self.stripe_subscription_link = None
            self.save(update_fields=['stripe_subscription_link'])

    def delete(self, *args, **kwargs):
        """Delete invoice and reverse any related inventory transactions."""
        with transaction.atomic():
            for line_item in self.income_records.all():
                line_item.delete()
            super(GroupedInvoice, self).delete(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_number} - {self.date} - {self.bill_to} - ${self.total_amount:.2f}"

    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "invoice_number"],
                name="unique_invoice_number_per_user",
                condition=~models.Q(invoice_number__isnull=True),
            ),
            models.UniqueConstraint(
                fields=['user', 'quickbooks_invoice_id'],
                name='unique_quickbooks_invoice_per_user',
                condition=~models.Q(quickbooks_invoice_id__isnull=True),
            )
        ]

class PendingInvoice(models.Model):
    grouped_invoice = models.OneToOneField(GroupedInvoice, on_delete=models.CASCADE, related_name='pending_invoice')
    date_created = models.DateTimeField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)

    def get_total_amount(self):
        return self.grouped_invoice.total_amount

    get_total_amount.short_description = 'Total Amount'

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.is_paid:
            try:
                # Transfer jobs to PaidInvoice
                paid_invoice, created = PaidInvoice.objects.get_or_create(grouped_invoice=self.grouped_invoice)

                if created:
                    jobs = IncomeRecord2.objects.filter(grouped_invoice=self.grouped_invoice)
                    for job in jobs:
                        job.pending_invoice = None
                        job.paid_invoice = paid_invoice
                        job.save()
                    # Delete the pending invoice
                    super(PendingInvoice, self).delete(*args, **kwargs)
                else:
                    print(f"Invoice {self.grouped_invoice.invoice_number} is already marked as paid.")
            except IntegrityError:
                transaction.rollback()
                print(f"IntegrityError: Invoice {self.grouped_invoice.invoice_number} could not be marked as paid due to a uniqueness constraint.")
        else:
            super(PendingInvoice, self).save(*args, **kwargs)

    def __str__(self):
        return f'Pending Invoice: {self.grouped_invoice.invoice_number}'

    class Meta:
        verbose_name = "Pending Invoice"
        verbose_name_plural = "Pending Invoices"

class PaidInvoice(models.Model):
    grouped_invoice = models.OneToOneField(GroupedInvoice, on_delete=models.CASCADE, related_name='paid_invoice')
    date_paid = models.DateTimeField(auto_now_add=True)

    def get_total_amount(self):
        return self.grouped_invoice.total_amount

    get_total_amount.short_description = 'Total Amount'

    def __str__(self):
        return f'Paid Invoice: {self.grouped_invoice.invoice_number}'

    class Meta:
        verbose_name = "Paid Invoice"
        verbose_name_plural = "Paid Invoices"

class Payment(models.Model):
    invoice = models.ForeignKey(GroupedInvoice, on_delete=models.CASCADE, related_name='payments')
    date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=50, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.date:
            self.date = date.today()  # Use date.today() if you've imported date
        super().save(*args, **kwargs)
        self.invoice.update_date_fully_paid()


    def __str__(self):
        return f'Payment of ${self.amount} on {self.date} for Invoice {self.invoice.invoice_number}'

class CategoryGroup(models.Model):
    user = models.ForeignKey(User, related_name='category_groups', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='category_group_images/', blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_category_group_name_per_user',
            ),
        ]

    def __str__(self):
        return self.name


class Category(models.Model):
    user = models.ForeignKey(User, related_name='categories', on_delete=models.CASCADE)
    group = models.ForeignKey(
        CategoryGroup,
        related_name='categories',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    parent = models.ForeignKey(
        'self',
        related_name='children',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='category_images/', blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_category_name_per_user',
            ),
        ]

    def __str__(self):
        return self.name


ATTRIBUTE_TYPE_CHOICES = (
    ('select', 'Select'),
    ('text', 'Text'),
    ('number', 'Number'),
    ('boolean', 'Yes/No'),
)


class CategoryAttribute(models.Model):
    user = models.ForeignKey(User, related_name='category_attributes', on_delete=models.CASCADE)
    category = models.ForeignKey(Category, related_name='attributes', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    value_unit = models.CharField(max_length=40, blank=True, null=True)
    attribute_type = models.CharField(max_length=20, choices=ATTRIBUTE_TYPE_CHOICES, default='select')
    is_filterable = models.BooleanField(default=True)
    is_comparable = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('category'),
                name='unique_attribute_name_per_category',
            ),
        ]

    def __str__(self):
        return self.name


class CategoryAttributeOption(models.Model):
    attribute = models.ForeignKey(CategoryAttribute, related_name='options', on_delete=models.CASCADE)
    value = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'value']
        constraints = [
            models.UniqueConstraint(
                Lower('value'),
                F('attribute'),
                name='unique_attribute_option_per_attribute',
            ),
        ]

    def __str__(self):
        return self.value

class Supplier(models.Model):
    user = models.ForeignKey(User, related_name='suppliers', on_delete=models.CASCADE)
    portal_user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='supplier_portal',
        help_text='Login account for this supplier',
    )
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_supplier_name_per_user',
            ),
        ]

    def __str__(self):
        return self.name


class ServiceJobName(models.Model):
    """Represents a logical grouping for one or more service descriptions."""

    user = models.ForeignKey(User, related_name='service_job_names', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_service_job_name_per_user',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.name:
            normalized = re.sub(r'\s+', ' ', self.name).strip()
            self.name = normalized
        super().save(*args, **kwargs)


class Service(models.Model):
    """Catalog of reusable job/service descriptions, grouped by a job name."""

    user = models.ForeignKey(User, related_name='services', on_delete=models.CASCADE)
    job_name = models.ForeignKey(
        ServiceJobName,
        related_name='services',
        on_delete=models.CASCADE,
    )
    name = models.TextField()
    description = models.TextField(blank=True)
    fixed_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        help_text='Optional default quantity to apply when this service is selected.',
    )
    fixed_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text='Optional default rate/price to apply when this service is selected.',
    )
    due_after_kilometers = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text='Optional interval in kilometers after which this service is due.',
    )
    due_after_months = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text='Optional interval in months after which this service is due.',
    )
    show_on_customer_portal = models.BooleanField(
        default=False,
        help_text="Display this service as a column in the customer vehicle list.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['job_name__name', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('job_name'),
                name='unique_service_description_per_job_name',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.name is not None:
            self.name = self._normalize_text(self.name)
        super().save(*args, **kwargs)

    @staticmethod
    def _normalize_text(value):
        raw_value = str(value or '')
        normalized_newlines = re.sub(r'\r\n?', '\n', raw_value)
        lines = normalized_newlines.split('\n')
        cleaned_lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in lines]

        while cleaned_lines and cleaned_lines[0] == '':
            cleaned_lines.pop(0)
        while cleaned_lines and cleaned_lines[-1] == '':
            cleaned_lines.pop()

        return '\n'.join(cleaned_lines)

    @staticmethod
    def _normalize_job_name(value):
        return re.sub(r'\s+', ' ', str(value or '')).strip()

    @staticmethod
    def _normalize_fixed_hours(value):
        """Return a Decimal rounded to two places for valid fixed hour values."""
        if value in (None, '', []):
            return None

        try:
            hours = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

        if hours < 0:
            return None

        return hours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def _normalize_fixed_rate(value):
        """Return a Decimal rounded to two places for valid fixed rate values."""
        if value in (None, '', []):
            return None

        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

        if amount < 0:
            return None

        return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    def record_service(
        cls,
        *,
        user,
        name,
        job_name=None,
        description=None,
        fixed_hours=None,
        fixed_rate=None,
        due_after_kilometers=None,
        due_after_months=None,
    ):
        """Ensure the provided job description is stored for the given business."""
        if not user or not name:
            return None

        normalized_name = cls._normalize_text(name)
        if not normalized_name:
            return None

        if isinstance(fixed_hours, str):
            fixed_hours = fixed_hours.strip()

        fixed_hours_provided = fixed_hours not in (None, '', [])
        normalized_fixed_hours = None
        if fixed_hours_provided:
            normalized_fixed_hours = cls._normalize_fixed_hours(fixed_hours)

        if isinstance(fixed_rate, str):
            fixed_rate = fixed_rate.strip()

        fixed_rate_provided = fixed_rate not in (None, '', [])
        normalized_fixed_rate = None
        if fixed_rate_provided:
            normalized_fixed_rate = cls._normalize_fixed_rate(fixed_rate)

        if isinstance(due_after_kilometers, str):
            due_after_kilometers = due_after_kilometers.strip()
        if isinstance(due_after_months, str):
            due_after_months = due_after_months.strip()

        def _normalize_positive_value(value):
            if value in (None, '', []):
                return None
            try:
                normalized_value = int(value)
            except (TypeError, ValueError):
                return None
            return normalized_value if normalized_value >= 0 else None

        normalized_due_kilometers = _normalize_positive_value(due_after_kilometers)
        normalized_due_months = _normalize_positive_value(due_after_months)

        job_group = None
        normalized_job_name = None

        if isinstance(job_name, ServiceJobName):
            if job_name.user_id == getattr(user, 'id', None):
                job_group = job_name
            else:
                normalized_job_name = cls._normalize_job_name(job_name.name)
        elif job_name is not None:
            try:
                job_name_id = int(job_name)
            except (TypeError, ValueError):
                job_name_id = None

            if job_name_id:
                job_group = ServiceJobName.objects.filter(user=user, pk=job_name_id).first()
            if not job_group:
                normalized_job_name = cls._normalize_job_name(job_name)

        if not job_group:
            if not normalized_job_name:
                normalized_job_name = normalized_name or 'General'
            job_group = ServiceJobName.objects.filter(user=user, name__iexact=normalized_job_name).first()
            if not job_group:
                job_group = ServiceJobName(user=user, name=normalized_job_name or 'General')
                try:
                    job_group.save()
                except IntegrityError:
                    job_group = ServiceJobName.objects.filter(user=user, name__iexact=normalized_job_name).first()
                if not job_group:
                    return None

        existing = cls.objects.filter(user=user, job_name=job_group, name__iexact=normalized_name).first()
        if existing:
            updates = []
            if description is not None and (existing.description or '') != description:
                existing.description = description
                updates.append('description')
            if fixed_hours_provided and existing.fixed_hours != normalized_fixed_hours:
                existing.fixed_hours = normalized_fixed_hours
                updates.append('fixed_hours')
            if fixed_rate_provided and existing.fixed_rate != normalized_fixed_rate:
                existing.fixed_rate = normalized_fixed_rate
                updates.append('fixed_rate')
            if (
                normalized_due_kilometers is not None
                and existing.due_after_kilometers != normalized_due_kilometers
            ):
                existing.due_after_kilometers = normalized_due_kilometers
                updates.append('due_after_kilometers')
            if normalized_due_months is not None and existing.due_after_months != normalized_due_months:
                existing.due_after_months = normalized_due_months
                updates.append('due_after_months')
            if not existing.is_active:
                existing.is_active = True
                updates.append('is_active')
            if updates:
                existing.save(update_fields=updates)
            return existing

        return cls.objects.create(
            user=user,
            job_name=job_group,
            name=normalized_name,
            description=description or '',
            fixed_hours=normalized_fixed_hours,
            fixed_rate=normalized_fixed_rate,
            due_after_kilometers=normalized_due_kilometers,
            due_after_months=normalized_due_months,
        )


class ServiceDescription(models.Model):
    """Additional descriptions for services to provide dropdown options."""
    service = models.ForeignKey(
        Service,
        related_name='additional_descriptions',
        on_delete=models.CASCADE,
    )
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    usage_count = models.PositiveIntegerField(default=0)  # Track how often this description is used

    class Meta:
        unique_together = ("service", "description")
        ordering = ['-usage_count', '-created_at']  # Most used and newest first

    def __str__(self):
        return f"{self.service.name}: {self.description[:50]}..."

    def increment_usage(self):
        """Increment usage count when this description is selected."""
        self.usage_count += 1
        self.save(update_fields=['usage_count'])


class InventoryLocation(models.Model):
    """Storage location that belongs to a business user."""

    user = models.ForeignKey(User, related_name="inventory_locations", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_location_name_per_user',
            ),
        ]

    def __str__(self):
        return self.name


class ProductBrand(models.Model):
    user = models.ForeignKey(User, related_name='product_brands', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    logo = models.ImageField(upload_to='brand_logos/', blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_brand_name_per_user',
            ),
        ]

    def __str__(self):
        return self.name


class ProductModel(models.Model):
    user = models.ForeignKey(User, related_name='product_models', on_delete=models.CASCADE)
    brand = models.ForeignKey(
        ProductBrand,
        related_name='models',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    year_start = models.PositiveIntegerField(blank=True, null=True)
    year_end = models.PositiveIntegerField(blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                F('user'),
                name='unique_model_name_per_user',
            ),
        ]

    def __str__(self):
        if self.brand:
            return f"{self.brand.name} {self.name}"
        return self.name


class ProductVin(models.Model):
    user = models.ForeignKey(User, related_name='product_vins', on_delete=models.CASCADE)
    vin = models.CharField(max_length=17)
    description = models.TextField(blank=True, null=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'vin']
        constraints = [
            models.UniqueConstraint(
                Lower('vin'),
                F('user'),
                name='unique_vin_per_user',
            ),
        ]

    def __str__(self):
        return self.vin


PRODUCT_TYPE_CHOICES = (
    ('inventory', 'Inventory'),
    ('non_inventory', 'Non-inventory'),
)

ALTERNATE_SKU_KIND_CHOICES = (
    ('interchange', 'Interchange'),
    ('equivalent', 'Equivalent'),
    ('alternate', 'Alternate'),
    ('oem', 'OEM'),
)

class Product(models.Model):
    user = models.ForeignKey(User, related_name='products', on_delete=models.CASCADE)
    sku = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    item_type = models.CharField(
        max_length=20,
        choices=PRODUCT_TYPE_CHOICES,
        default='inventory',
    )
    category = models.ForeignKey(Category, related_name='products', on_delete=models.SET_NULL, null=True)
    supplier = models.ForeignKey(Supplier, related_name='products', on_delete=models.SET_NULL, null=True)
    brand = models.ForeignKey(
        ProductBrand,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    vehicle_model = models.ForeignKey(
        ProductModel,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    vin_number = models.ForeignKey(
        ProductVin,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    quickbooks_item_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Identifier for the matching product in QuickBooks.",
    )
    source_name = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        help_text="Origin source for imported product data (e.g., Traction).",
    )
    source_url = models.URLField(
        blank=True,
        null=True,
        help_text="Source URL for imported product data.",
    )
    source_product_id = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Source product identifier from the import origin.",
    )
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    promotion_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional promotional price shown on the storefront.",
    )
    margin = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity_in_stock = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="product_images/", blank=True, null=True)
    is_published_to_store = models.BooleanField(
        default=False,
        help_text="Display this product on your public storefront.",
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Highlight this product in featured storefront sections.",
    )
    warranty_expiry_date = models.DateField(blank=True, null=True)
    warranty_length = models.PositiveIntegerField(blank=True, null=True, help_text="Warranty length in days")
    location = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.sku:
            return f"{self.name} ({self.sku})"
        return self.name

    @property
    def is_below_reorder_level(self):
        if self.item_type != 'inventory':
            return False
        return self.quantity_in_stock < self.reorder_level

    @property
    def has_promotion(self):
        if self.promotion_price is None:
            return False
        if self.sale_price is None:
            return True
        return self.promotion_price < self.sale_price

    @property
    def promotion_discount_percent(self):
        if not self.has_promotion or self.sale_price is None or self.promotion_price is None:
            return None
        sale_price = ensure_decimal(self.sale_price)
        promo_price = ensure_decimal(self.promotion_price)
        if sale_price <= Decimal('0.00'):
            return None
        discount = ((sale_price - promo_price) / sale_price) * Decimal('100')
        return int(discount.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    @property
    def storefront_price(self):
        return self.promotion_price if self.promotion_price is not None else self.sale_price

    @staticmethod
    def get_low_stock_products(user):
        """
        Returns products for a given user that are below their reorder level.
        """
        from .utils import annotate_products_with_stock, get_product_user_ids

        product_user_ids = get_product_user_ids(user)
        products = Product.objects.filter(user__in=product_user_ids, item_type='inventory')
        products = annotate_products_with_stock(products, user)
        return products.filter(stock_quantity__lt=F('stock_reorder'))

    @staticmethod
    def top_sellers(user, days=30, limit=5):
        start = timezone.now() - timedelta(days=days)
        return (
            Product.objects.filter(user=user)
            .annotate(
                qty_sold=Sum(
                    'transactions__quantity',
                    filter=Q(transactions__transaction_type='OUT',
                            transactions__transaction_date__gte=start)
                )
            )
            .order_by('-qty_sold')[:limit]
        )

    @staticmethod
    def slow_movers(user, days=30, limit=5):
        start = timezone.now() - timedelta(days=days)
        return (
            Product.objects.filter(user=user)
            .annotate(
                qty_sold=Sum(
                    'transactions__quantity',
                    filter=Q(transactions__transaction_type='OUT',
                            transactions__transaction_date__gte=start)
                )
            )
            .order_by('qty_sold')[:limit]
        )

    @staticmethod
    def get_unsold_products(user, days=180):
        cutoff = timezone.now() - timedelta(days=days)
        return (
            Product.objects.filter(user=user)
            .annotate(
                last_sale=Max(
                    'transactions__transaction_date',
                    filter=Q(transactions__transaction_type='OUT')
                )
            )
            .filter(Q(last_sale__lt=cutoff) | Q(last_sale__isnull=True))
        )

    @staticmethod
    def get_expiring_warranty_products(user, days_ahead=30):
        target_date = timezone.now().date() + timedelta(days=days_ahead)
        return Product.objects.filter(
            user=user,
            warranty_expiry_date__lte=target_date,
            warranty_expiry_date__gte=timezone.now().date(),
        )

    def _apply_default_margin(self):
        """Populate sale price using the profile margin percentage when possible."""
        if self.sale_price is not None:
            return

        if self.cost_price is None or not self.user_id:
            return

        profile = getattr(self.user, "profile", None)
        if not profile:
            return

        margin_percent = profile.default_inventory_margin_percent
        if margin_percent is None:
            return

        margin_percent = Decimal(margin_percent)
        if margin_percent < Decimal("0"):
            return

        multiplier = Decimal("1") + (margin_percent / Decimal("100"))
        sale = (self.cost_price * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.sale_price = sale
        self.margin = sale - self.cost_price

    def _ensure_pricing_consistency(self):
        """Ensure cost, sale, and margin values stay in sync."""
        cost = self.cost_price
        sale = self.sale_price
        margin = self.margin

        if margin is not None and cost is None and sale is not None:
            cost = sale - margin
        if margin is not None and sale is None and cost is not None:
            sale = cost + margin

        if cost is not None and sale is not None:
            margin = sale - cost
        elif margin is not None:
            if cost is None and sale is not None:
                cost = sale - margin
            if sale is None and cost is not None:
                sale = cost + margin

        self.cost_price = cost
        self.sale_price = sale
        self.margin = margin

    def _validate_pricing(self, allow_missing_sale=False):
        if self.cost_price is None:
            raise ValidationError("Cost price cannot be empty.")

        if not allow_missing_sale and self.sale_price is None:
            raise ValidationError(
                "Sale price cannot be empty. Set a price, margin, or configure a default profile margin."
            )

        if self.cost_price < Decimal("0"):
            raise ValidationError("Cost price cannot be negative.")

        if self.sale_price is not None and self.sale_price < Decimal("0"):
            raise ValidationError("Sale price cannot be negative.")

        if self.promotion_price is not None:
            if self.promotion_price < Decimal("0"):
                raise ValidationError("Promotion price cannot be negative.")
            if self.sale_price is not None and self.promotion_price > self.sale_price:
                raise ValidationError("Promotion price must be less than or equal to sale price.")

    def clean(self):
        super().clean()
        self._apply_default_margin()
        self._ensure_pricing_consistency()

        allow_missing_sale = not bool(self.user_id)
        self._validate_pricing(allow_missing_sale=allow_missing_sale)

    def save(self, *args, **kwargs):
        self._apply_default_margin()
        self._ensure_pricing_consistency()
        self._validate_pricing(allow_missing_sale=False)
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('sku'),
                F('user'),
                name='unique_product_sku_per_user',
                condition=Q(sku__isnull=False) & ~Q(sku=''),
            ),
            models.UniqueConstraint(
                fields=['user', 'quickbooks_item_id'],
                name='unique_product_quickbooks_item_per_user',
            ),
        ]


class ProductStock(models.Model):
    product = models.ForeignKey(
        Product,
        related_name="stock_levels",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="product_stocks",
        on_delete=models.CASCADE,
    )
    quantity_in_stock = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "user"], name="unique_product_stock_per_user"),
        ]

    def __str__(self):
        owner = self.user.get_full_name() or self.user.get_username()
        return f"{self.product.name} - {owner}"


def _resolve_stock_owner(user, product=None):
    if user:
        profile = getattr(user, "profile", None)
        business_user = user
        if profile and hasattr(profile, "get_business_user"):
            business_user = profile.get_business_user() or user

        group = ConnectedBusinessGroup.objects.filter(members=business_user).first()

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
    if product:
        return product.user
    return None


class ProductAlternateSku(models.Model):
    product = models.ForeignKey(
        Product,
        related_name='alternate_skus',
        on_delete=models.CASCADE,
    )
    sku = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=20,
        choices=ALTERNATE_SKU_KIND_CHOICES,
        default='interchange',
    )
    source_name = models.CharField(max_length=40, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('sku'),
                F('product'),
                name='unique_alternate_sku_per_product',
            ),
        ]

    def __str__(self):
        return f"{self.sku} ({self.get_kind_display()})"


class ProductAttributeValue(models.Model):
    product = models.ForeignKey(Product, related_name='attribute_values', on_delete=models.CASCADE)
    attribute = models.ForeignKey(
        CategoryAttribute,
        related_name='product_values',
        on_delete=models.CASCADE,
    )
    option = models.ForeignKey(
        CategoryAttributeOption,
        related_name='product_values',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    value_text = models.CharField(max_length=200, blank=True)
    value_number = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'attribute'],
                name='unique_product_attribute_value',
            ),
        ]

    def __str__(self):
        return f"{self.product_id} - {self.attribute.name}"

    def get_display_value(self):
        if self.value_boolean is not None:
            return "Yes" if self.value_boolean else "No"
        if self.option_id:
            value = self.option.value
        elif self.value_text:
            value = self.value_text
        elif self.value_number is not None:
            value = str(self.value_number)
        else:
            value = ""
        unit = self.attribute.value_unit if self.attribute and self.attribute.value_unit else ""
        if value and unit:
            return f"{value} {unit}"
        return value


HERO_GRADIENT_CHOICES = (
    ('sky', 'Sky Blue'),
    ('sunrise', 'Sunrise Glow'),
    ('mint', 'Mint Breeze'),
    ('sand', 'Soft Sand'),
    ('ice', 'Icy Light'),
)

BANNER_THEME_CHOICES = HERO_GRADIENT_CHOICES


class StorefrontHeroShowcase(models.Model):
    user = models.OneToOneField(
        User,
        related_name='storefront_hero_showcase',
        on_delete=models.CASCADE,
    )
    gradient_theme = models.CharField(
        max_length=20,
        choices=HERO_GRADIENT_CHOICES,
        default='sky',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Storefront hero showcase'
        verbose_name_plural = 'Storefront hero showcases'

    def __str__(self):
        return f"{self.user.username} - Hero Showcase"


class StorefrontHeroShowcaseItem(models.Model):
    hero = models.ForeignKey(
        StorefrontHeroShowcase,
        related_name='slides',
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        Product,
        related_name='hero_showcase_items',
        on_delete=models.CASCADE,
    )
    discount_percent = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Optional discount badge shown on the hero slide.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['hero', 'product'],
                name='unique_hero_showcase_product',
            ),
        ]

    def __str__(self):
        return f"{self.hero_id} - {self.product_id}"


class StorefrontHeroPackage(models.Model):
    user = models.ForeignKey(
        User,
        related_name='storefront_hero_packages',
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True)
    primary_product = models.ForeignKey(
        Product,
        related_name='hero_package_primary',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    secondary_product = models.ForeignKey(
        Product,
        related_name='hero_package_secondary',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    free_product = models.ForeignKey(
        Product,
        related_name='hero_package_free',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    discount_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Storefront hero package'
        verbose_name_plural = 'Storefront hero packages'

    def __str__(self):
        return f"{self.user.username} - {self.title}"


class StorefrontMessageBanner(models.Model):
    user = models.OneToOneField(
        User,
        related_name='storefront_message_banner',
        on_delete=models.CASCADE,
    )
    is_active = models.BooleanField(default=False)
    message = models.CharField(max_length=240, blank=True)
    link_text = models.CharField(max_length=80, blank=True)
    link_url = models.CharField(max_length=200, blank=True)
    theme = models.CharField(
        max_length=20,
        choices=BANNER_THEME_CHOICES,
        default='sunrise',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Storefront message banner'
        verbose_name_plural = 'Storefront message banners'

    def __str__(self):
        return f"{self.user.username} - Message Banner"


class StorefrontFlyer(models.Model):
    user = models.OneToOneField(
        User,
        related_name='storefront_flyer',
        on_delete=models.CASCADE,
    )
    is_active = models.BooleanField(default=False)
    title = models.CharField(max_length=120, blank=True)
    subtitle = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Storefront flyer'
        verbose_name_plural = 'Storefront flyers'

    def __str__(self):
        return f"{self.user.username} - Storefront Flyer"


class InventoryTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
        ('ADJUSTMENT', 'Adjustment'),
    )

    product = models.ForeignKey(Product, related_name='transactions', on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity = models.PositiveIntegerField()
    transaction_date = models.DateTimeField(default=timezone.now)
    remarks = models.TextField(blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="inventory_transactions")

    def __str__(self):
        return f"{self.product.name} - {self.transaction_type} - {self.quantity}"

    def save(self, *args, **kwargs):
        if not self.product or getattr(self.product, 'item_type', 'inventory') != 'inventory':
            super(InventoryTransaction, self).save(*args, **kwargs)
            return

        stock_owner = _resolve_stock_owner(self.user, self.product)
        if not stock_owner:
            super(InventoryTransaction, self).save(*args, **kwargs)
            return

        if not self.user_id:
            self.user = stock_owner

        stock_record, _ = ProductStock.objects.get_or_create(
            product=self.product,
            user=stock_owner,
            defaults={"quantity_in_stock": 0, "reorder_level": 0},
        )
        current_stock = stock_record.quantity_in_stock or 0

        if self.transaction_type == 'IN':
            stock_record.quantity_in_stock = current_stock + self.quantity
        elif self.transaction_type == 'OUT':
            if current_stock < self.quantity:
                # Auto-top-up missing stock instead of throwing an error
                missing_qty = self.quantity - current_stock
                InventoryTransaction.objects.create(
                    product=self.product,
                    transaction_type='IN',
                    quantity=missing_qty,
                    transaction_date=timezone.now(),
                    remarks="Auto restock to satisfy invoice",
                    user=self.user,
                )
                current_stock += missing_qty
            stock_record.quantity_in_stock = current_stock - self.quantity
        elif self.transaction_type == 'ADJUSTMENT':
            stock_record.quantity_in_stock = self.quantity

        stock_record.save(update_fields=["quantity_in_stock", "updated_at"])
        if stock_owner.id == self.product.user_id:
            Product.objects.filter(pk=self.product_id).update(
                quantity_in_stock=stock_record.quantity_in_stock,
            )
        super(InventoryTransaction, self).save(*args, **kwargs)



class IncomeRecord2(models.Model):
    grouped_invoice = models.ForeignKey('GroupedInvoice', null=True, on_delete=models.CASCADE, related_name='income_records') # Assuming GroupedInvoice is defined above
    pending_invoice = models.ForeignKey('PendingInvoice', null=True, blank=True, on_delete=models.SET_NULL, related_name='income_records') # Assuming PendingInvoice is defined above
    paid_invoice = models.ForeignKey('PaidInvoice', null=True, blank=True, on_delete=models.SET_NULL, related_name='income_records') # Assuming PaidInvoice is defined above
    payment = models.ForeignKey('Payment', null=True, blank=True, on_delete=models.SET_NULL, related_name='income_records') # Assuming Payment is defined above
    product = models.ForeignKey('Product', null=True, blank=True, on_delete=models.SET_NULL) # Assuming Product is defined above
    job = models.CharField(max_length=2000, blank=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), null=True) # Default to Decimal
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), null=True) # Default to Decimal
    amount = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=Decimal('0.00')) # Default to Decimal
    tax_collected = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=Decimal('0.00')) # Default to Decimal
    line_order = models.PositiveIntegerField(default=0)

    # Fields specific to contractors
    date = models.DateField(null=True, blank=True)
    ticket = models.CharField(max_length=16, null=True)
    jobsite = models.CharField(max_length=16, null=True)
    truck = models.CharField(max_length=16, null=True)
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, blank=True, null=True) # Assuming Driver is defined above
    quickbooks_line_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Identifier for the matching line item in QuickBooks.",
    )

    _original_product_id = None
    _original_qty = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store original values only if it's an existing instance loaded from DB
        if self.pk:
            self._original_product_id = self.product_id
        # Always normalize the stored quantity value
        self._original_qty = ensure_decimal(getattr(self, 'qty', None))


    def _create_inventory_transaction(self, transaction_type, quantity, product_override=None, remarks_suffix="", user=None):
        """Helper to create inventory transaction."""
        product_to_use = product_override if product_override else self.product
        if not product_to_use or quantity is None or quantity <= 0:
            return # Don't log if no product or zero/negative quantity
        if getattr(product_to_use, 'item_type', 'inventory') != 'inventory':
            return

        if remarks_suffix.lower() == "sold":
            if self.grouped_invoice:
                remarks = f"Sold with invoice {self.grouped_invoice.invoice_number}"
            else:
                remarks = "Sold"
        else:
            remarks_base = f"Invoice {self.grouped_invoice.invoice_number}" if self.grouped_invoice else "Invoice N/A"
            remarks = f"{remarks_base} - {remarks_suffix}"

        owner_user = user or (self.grouped_invoice.user if self.grouped_invoice else None) or getattr(product_to_use, "user", None)

        # Ensure quantity is a whole number for the InventoryTransaction model
        # which uses a PositiveIntegerField
        trans_qty = Decimal(str(quantity)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        trans_qty_int = int(trans_qty)

        if trans_qty_int > 0:  # Only create if there's a positive quantity change
            InventoryTransaction.objects.create(
                product=product_to_use,
                transaction_type=transaction_type,
                quantity=trans_qty_int,
                transaction_date=timezone.now(),
                remarks=remarks.strip(),
                user=owner_user,
            )

    def save(self, *args, **kwargs):
        # --- Calculate amount and tax (your existing logic) ---
        qty_dec = ensure_decimal(self.qty)
        rate_dec = ensure_decimal(self.rate)
        calculated_amount = (qty_dec * rate_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.amount = calculated_amount

        is_interest = self.job and str(self.job).lower().startswith('interest')

        if self.grouped_invoice and self.grouped_invoice.user and hasattr(self.grouped_invoice.user, 'profile'):
            user_profile = self.grouped_invoice.user.profile
            if is_interest or (self.grouped_invoice and self.grouped_invoice.tax_exempt):
                self.tax_collected = Decimal('0.00')
            else:
                self.tax_collected = calculate_tax_total(self.amount, user_profile.province)
        else:
            self.tax_collected = Decimal('0.00')
        # --- End calculation logic ---


        # --- Inventory Transaction Logic ---
        is_new = self.pk is None
        if is_new and (self.line_order is None or self.line_order <= 0) and self.grouped_invoice_id:
            max_order = (
                IncomeRecord2.objects.filter(grouped_invoice_id=self.grouped_invoice_id)
                .aggregate(max_order=Max('line_order'))
                .get('max_order')
                or 0
            )
            self.line_order = max_order + 1
        current_product_id = self.product_id
        current_qty = ensure_decimal(self.qty)

        # Temporarily store original values before super().save() overwrites them if is_new
        original_product_id = self._original_product_id
        original_qty = ensure_decimal(self._original_qty)

        # Save the record *first*
        super().save(*args, **kwargs)

        # Now handle inventory changes using the stored original values
        product_changed = original_product_id != current_product_id
        qty_changed = original_qty != current_qty

        if product_changed or qty_changed:
            # 1. Reverse old transaction if product existed previously
            if original_product_id is not None and original_qty > 0:
                try:
                    original_product = Product.objects.get(pk=original_product_id)
                    self._create_inventory_transaction(
                        'IN',
                        original_qty,
                        original_product,
                        remarks_suffix="Reversed",
                        user=(self.grouped_invoice.user if self.grouped_invoice else None) or (original_product.user if original_product else None),
                    )
                except Product.DoesNotExist:
                    # Log error or handle case where original product might have been deleted
                    print(f"Warning: Original product ID {original_product_id} not found for reversal.")


            # 2. Create new transaction if product exists now
            if current_product_id is not None and current_qty > 0:
                 # No need to fetch product again, self.product is updated
                self._create_inventory_transaction(
                    'OUT',
                    current_qty,
                    self.product,
                    remarks_suffix="Sold",
                    user=(self.grouped_invoice.user if self.grouped_invoice else None) or (self.product.user if self.product else None),
                )


        # Update the internal tracking fields *after* handling transactions for this save
        self._original_product_id = self.product_id
        self._original_qty = ensure_decimal(self.qty)
        # --- End Inventory Logic ---


        # Recalculate parent invoice total *after* this record is saved and inventory adjusted
        if self.grouped_invoice:
            # Post-save signal might be cleaner, but direct call works if no circular dependencies
            # Be cautious if recalculate_total_amount itself calls save() recursively
            # Using update_fields in recalculate_total_amount helps prevent loops.
            self.grouped_invoice.recalculate_total_amount()

    def delete(self, *args, **kwargs):
        # Store necessary info before deletion
        product_to_reverse = self.product
        qty_to_reverse = ensure_decimal(self.qty)
        grouped_invoice_instance = self.grouped_invoice # Keep reference for recalculation

        # --- Inventory Reversal Logic ---
        if product_to_reverse is not None and qty_to_reverse > 0:
            # Create an 'IN' transaction to reverse the stock removal
            self._create_inventory_transaction(
                'IN',
                qty_to_reverse,
                product_to_reverse,
                remarks_suffix="Deletion Reversal",
                user=(self.grouped_invoice.user if self.grouped_invoice else None) or (product_to_reverse.user if product_to_reverse else None),
            )
        # --- End Inventory Logic ---

        # Delete the record itself
        super().delete(*args, **kwargs)

        # Recalculate parent invoice total *after* this record is deleted
        if grouped_invoice_instance:
            try:
                # Call using the stored reference
                grouped_invoice_instance.recalculate_total_amount()
            except AttributeError:
                 print(f"Warning: Could not recalculate total for GroupedInvoice ID {grouped_invoice_instance.id} after delete")
                 pass # Or log appropriately


    def __str__(self):
        invoice_num = self.grouped_invoice.invoice_number if self.grouped_invoice else 'N/A'
        amount_val = self.amount if self.amount is not None else Decimal('0.00')
        # Improved str representation:
        details = f"Job: {self.job}" if self.job else f"Product: {self.product}" if self.product else "Line Item"
        return f'{invoice_num} - {details} - Qty: {self.qty}, Rate: {self.rate}, Amt: ${amount_val:.2f}'


    class Meta:
        verbose_name = "Invoice Line Item" # Changed for clarity
        verbose_name_plural = "Invoice Line Items"
        ordering = ['line_order', 'id']


class DriverSettlementStatement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    driver = models.ForeignKey('Driver', on_delete=models.CASCADE)
    date_created = models.DateField(auto_now_add=True)
    date_from = models.DateField()
    date_to = models.DateField()
    # settlement_total now represents the subtotal (activities only)
    settlement_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def update_totals(self):
        subtotal = Decimal('0.00')
        tax_total = Decimal('0.00')
        # Sum up the activity amounts
        for activity in self.activities.all():
            qty = ensure_decimal(activity.qty)
            rate = ensure_decimal(activity.rate)
            act_amount = (qty * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            subtotal += act_amount

        # Only calculate tax if the driver is paid GST/HST
        if self.driver.pay_gst_hst:
            user_profile = self.user.profile
            for activity in self.activities.all():
                qty = ensure_decimal(activity.qty)
                rate = ensure_decimal(activity.rate)
                act_amount = (qty * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                tax_total += calculate_tax_total(act_amount, user_profile.province)
        else:
            tax_total = Decimal('0.00')

        self.tax_total = tax_total
        # Settlement total remains the subtotal; tax will be added in the frontend/PDF if needed.
        self.settlement_total = subtotal
        self.save(update_fields=['tax_total', 'settlement_total'])

    def __str__(self):
        return f"Settlement #{self.pk} for {self.driver.name}"

class DriverSettlementActivity(models.Model):
    settlement = models.ForeignKey(DriverSettlementStatement, related_name='activities', on_delete=models.CASCADE)
    job = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    ticket = models.CharField(max_length=50, blank=True, null=True)
    jobsite = models.CharField(max_length=255, blank=True, null=True)
    truck = models.CharField(max_length=50, blank=True, null=True)

    @property
    def amount(self):
        return self.qty * self.rate

class GroupedEstimate(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, related_name='estimates')
    po_number = models.CharField(max_length=20, null=True, blank=True)
    date = models.DateField(null=True)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    bill_to = models.CharField(max_length=50, null=True)
    bill_to_address = models.TextField(null=True, blank=True)
    bill_to_email = models.EmailField(null=True)
    vin_no = models.CharField(max_length=17, null=True, blank=True)
    mileage = models.FloatField(null=True, blank=True)
    unit_no = models.CharField(max_length=64, null=True, blank=True)
    make_model = models.CharField(max_length=25, null=True, blank=True)
    estimate_number = models.CharField(max_length=20, blank=True, null=True, unique=True, editable=False)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    is_subscription = models.BooleanField(default=False)
    subscription_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, null=True, blank=True)
    tax_exempt = models.BooleanField(default=False)
    tax_exempt_reason = models.CharField(max_length=255, null=True, blank=True)

    def recalculate_total_amount(self):
        job_total = sum(
            (ensure_decimal(record.amount) for record in self.estimate_records.all()),
            Decimal('0.00'),
        )
        tax_total = sum(
            (ensure_decimal(record.tax_collected) for record in self.estimate_records.all()),
            Decimal('0.00'),
        )
        self.total_amount = (job_total + tax_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.save(update_fields=['total_amount'])

    @staticmethod
    def generate_estimate_number(user):
        with transaction.atomic():
            last_estimate = GroupedEstimate.objects.select_for_update().filter(user=user).order_by('-id').first()
            if last_estimate and last_estimate.estimate_number:
                try:
                    last_number = int(last_estimate.estimate_number.split('-')[-1])
                    new_number = last_number + 1
                except ValueError:
                    new_number = 150  # Default starting number
            else:
                new_number = 150
            return f'EST-{user.id}-{new_number:04d}'

    def save(self, *args, **kwargs):
        if not self.pk:  # When creating a new estimate
            if not self.estimate_number:
                self.estimate_number = self.generate_estimate_number(self.user)
        super().save(*args, **kwargs)

    def convert_to_invoice(self):
        """
        Converts this estimate to a real invoice by creating a GroupedInvoice instance
        and copying over the relevant fields and associated EstimateRecords as IncomeRecord2.
        """
        from accounts.models import GroupedInvoice, IncomeRecord2  # adjust import as needed

        with transaction.atomic():
            invoice = GroupedInvoice.objects.create(
                user=self.user,
                customer=self.customer,
                date=self.date,
                date_from=self.date_from,
                date_to=self.date_to,
                bill_to=self.bill_to,
                bill_to_address=self.bill_to_address,
                bill_to_email=self.bill_to_email,
                vin_no=self.vin_no,
                mileage=self.mileage,
                unit_no=self.unit_no,
                make_model=self.make_model,
            )
            # Copy each estimate record to a real invoice record.
            for record in self.estimate_records.all():
                IncomeRecord2.objects.create(
                    grouped_invoice=invoice,
                    product=record.product,
                    job=record.job,
                    qty=ensure_decimal(record.qty),
                    rate=ensure_decimal(record.rate),
                    date=record.date,
                    ticket=record.ticket,
                    jobsite=record.jobsite,
                    truck=record.truck,
                    driver=record.driver,
                )
            invoice.ensure_inventory_transactions()
            invoice.recalculate_total_amount()
            invoice.create_online_payment_link()  # Create payment link if applicable.
            return invoice

    def __str__(self):
        return f'{self.estimate_number} - {self.date} - {self.bill_to} - ${self.total_amount:.2f}'

    class Meta:
        verbose_name = "Estimate"
        verbose_name_plural = "Estimates"


class EstimateRecord(models.Model):
    grouped_estimate = models.ForeignKey(GroupedEstimate, null=True, on_delete=models.CASCADE, related_name='estimate_records')
    product = models.ForeignKey('Product', null=True, blank=True, on_delete=models.SET_NULL)
    job = models.CharField(max_length=2000, blank=True)
    qty = models.FloatField(default=0, null=True)
    rate = models.FloatField(default=0, null=True)
    amount = models.FloatField(editable=False, default=0)
    tax_collected = models.FloatField(editable=False, default=0)
    date = models.DateField(null=True, blank=True)
    ticket = models.CharField(max_length=16, null=True, blank=True)
    jobsite = models.CharField(max_length=16, null=True, blank=True)
    truck = models.CharField(max_length=16, null=True, blank=True)
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, blank=True, null=True)

    def save(self, *args, **kwargs):
        qty_dec = ensure_decimal(self.qty)
        rate_dec = ensure_decimal(self.rate)
        amount_dec = (qty_dec * rate_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.amount = float(amount_dec)
        user_profile = self.grouped_estimate.user.profile
        self.tax_collected = float(calculate_tax_total(amount_dec, user_profile.province))
        super().save(*args, **kwargs)
        if self.grouped_estimate:
            self.grouped_estimate.recalculate_total_amount()

    def __str__(self):
        return f'{self.grouped_estimate.estimate_number} - {self.job} - ${self.amount:.2f}'

    class Meta:
        verbose_name = "Estimate Record"
        verbose_name_plural = "Estimate Records"

class Mechanic(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    portal_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mechanic_portal",
        null=True,
        blank=True,
        help_text="Login account for this mechanic",
    )
    def __str__(self):
        return self.name


class MechanicSignupCode(models.Model):
    """Invite code generated by a business to allow a mechanic to sign up."""
    business = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mechanic_signup_codes",
    )
    code = models.CharField(max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    mechanic = models.ForeignKey(
        "Mechanic",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="signup_code",
    )

    def __str__(self):
        return self.code


# ---------------------------
# PAYROLL MODELS
# ---------------------------

class PayrollSettings(models.Model):
    PAY_PERIOD_WEEKLY = "weekly"
    PAY_PERIOD_BIWEEKLY = "biweekly"
    PAY_PERIOD_SEMIMONTHLY = "semimonthly"
    PAY_PERIOD_MONTHLY = "monthly"
    PAY_PERIOD_CHOICES = (
        (PAY_PERIOD_WEEKLY, "Weekly"),
        (PAY_PERIOD_BIWEEKLY, "Biweekly"),
        (PAY_PERIOD_SEMIMONTHLY, "Semimonthly"),
        (PAY_PERIOD_MONTHLY, "Monthly"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="payroll_settings")
    pay_period_frequency = models.CharField(
        max_length=16,
        choices=PAY_PERIOD_CHOICES,
        default=PAY_PERIOD_BIWEEKLY,
    )
    period_anchor_date = models.DateField(
        default=timezone.now,
        help_text="Anchor date for pay period calculations.",
    )
    default_pay_date_offset_days = models.PositiveIntegerField(
        default=0,
        help_text="Days after period end to set pay date.",
    )
    auto_approve_timesheets = models.BooleanField(default=False)
    overtime_enabled = models.BooleanField(default=False)
    overtime_daily_enabled = models.BooleanField(default=True)
    overtime_daily_threshold = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("8.00"))
    overtime_weekly_enabled = models.BooleanField(default=True)
    overtime_weekly_threshold = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("40.00"))
    overtime_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.50"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payroll settings for {self.user.username}"


class Employee(models.Model):
    ROLE_MECHANIC = "mechanic"
    ROLE_ADMIN = "admin"
    ROLE_OTHER = "other"
    ROLE_CHOICES = (
        (ROLE_MECHANIC, "Mechanic"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_OTHER, "Other"),
    )

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_TERMINATED = "terminated"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_TERMINATED, "Terminated"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="employees")
    mechanic = models.OneToOneField(
        Mechanic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_MECHANIC)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    hire_date = models.DateField(blank=True, null=True)
    termination_date = models.DateField(blank=True, null=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class EmployeeTaxProfile(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="tax_profile")
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES, default="ON")
    federal_claim_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    provincial_claim_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    additional_withholding = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    cpp_exempt = models.BooleanField(default=False)
    ei_exempt = models.BooleanField(default=False)
    cpp2_exempt = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Tax profile for {self.employee.full_name}"


class EmployeeRecurringDeduction(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="recurring_deductions")
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    is_pre_tax = models.BooleanField(default=False)
    is_employer_contribution = models.BooleanField(default=False)
    is_employee_contribution = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.employee.full_name})"


class ShiftTemplate(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shift_templates")
    name = models.CharField(max_length=120)
    start_time = models.TimeField()
    end_time = models.TimeField()
    notes = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Timesheet(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="timesheets")
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_timesheets")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_timesheets")
    approved_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "period_start", "period_end")

    def __str__(self):
        return f"{self.employee.full_name} {self.period_start} - {self.period_end}"


class TimeEntry(models.Model):
    timesheet = models.ForeignKey(Timesheet, on_delete=models.CASCADE, related_name="entries")
    work_date = models.DateField()
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("timesheet", "work_date")

    def _calculate_hours_from_times(self):
        if not self.start_time or not self.end_time:
            return None
        start_dt = datetime.datetime.combine(self.work_date, self.start_time)
        end_dt = datetime.datetime.combine(self.work_date, self.end_time)
        if end_dt < start_dt:
            end_dt += datetime.timedelta(days=1)
        seconds = (end_dt - start_dt).total_seconds()
        hours = Decimal(seconds) / Decimal("3600")
        return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        calculated = self._calculate_hours_from_times()
        if calculated is not None:
            self.hours = calculated
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.timesheet.employee.full_name} {self.work_date} {self.hours}h"


class TimesheetSnapshot(models.Model):
    SOURCE_MECHANIC = "mechanic"
    SOURCE_ADMIN = "admin"
    SOURCE_CHOICES = (
        (SOURCE_MECHANIC, "Mechanic submission"),
        (SOURCE_ADMIN, "Admin record"),
    )

    timesheet = models.ForeignKey(Timesheet, on_delete=models.CASCADE, related_name="snapshots")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timesheet_snapshots",
    )
    captured_at = models.DateTimeField(auto_now=True)
    total_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    entries = models.JSONField(default=list)

    class Meta:
        unique_together = ("timesheet", "source")

    def __str__(self):
        return f"{self.timesheet} ({self.get_source_display()})"


class PayrollRun(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payroll_runs")
    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_payroll_runs")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_payroll_runs")
    approved_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "period_start", "period_end")

    def __str__(self):
        return f"Payroll {self.period_start} - {self.period_end}"


class PayStub(models.Model):
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="paystubs")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="paystubs")
    hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    regular_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    regular_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    taxable_income = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    federal_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    provincial_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cpp_employee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cpp_employer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cpp2_employee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cpp2_employer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    ei_employee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    ei_employer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    employer_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("payroll_run", "employee")

    def __str__(self):
        return f"{self.employee.full_name} {self.payroll_run.period_end}"


class PayStubLineItem(models.Model):
    TYPE_EARNING = "earning"
    TYPE_DEDUCTION = "deduction"
    TYPE_BENEFIT = "benefit"
    TYPE_EMPLOYER_TAX = "employer_tax"
    TYPE_CHOICES = (
        (TYPE_EARNING, "Earning"),
        (TYPE_DEDUCTION, "Deduction"),
        (TYPE_BENEFIT, "Benefit"),
        (TYPE_EMPLOYER_TAX, "Employer Tax"),
    )

    paystub = models.ForeignKey(PayStub, on_delete=models.CASCADE, related_name="line_items")
    line_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    employer_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"{self.name} ({self.paystub.employee.full_name})"


class PayrollTaxYear(models.Model):
    year = models.PositiveIntegerField(unique=True)
    cpp_rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))
    cpp_basic_exemption = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    cpp_max_pensionable = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cpp2_rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))
    cpp2_max_pensionable = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    ei_rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))
    ei_max_insurable = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    ei_employer_multiplier = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("1.4000"))
    federal_basic_personal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return str(self.year)


class PayrollProvinceTaxSetting(models.Model):
    tax_year = models.ForeignKey(PayrollTaxYear, on_delete=models.CASCADE, related_name="province_settings")
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES)
    basic_personal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        unique_together = ("tax_year", "province")

    def __str__(self):
        return f"{self.tax_year.year} {self.province}"


class PayrollTaxBracket(models.Model):
    JURISDICTION_FEDERAL = "FED"
    JURISDICTION_CHOICES = (
        (JURISDICTION_FEDERAL, "Federal"),
    ) + tuple(PROVINCE_CHOICES)

    tax_year = models.ForeignKey(PayrollTaxYear, on_delete=models.CASCADE, related_name="brackets")
    jurisdiction = models.CharField(max_length=3, choices=JURISDICTION_CHOICES)
    bracket_min = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    bracket_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))

    class Meta:
        unique_together = ("tax_year", "jurisdiction", "bracket_min", "bracket_max")
        ordering = ["bracket_min"]

    def __str__(self):
        max_label = self.bracket_max if self.bracket_max is not None else "top"
        return f"{self.tax_year.year} {self.jurisdiction} {self.bracket_min}-{max_label}"


class PayrollEmployerTax(models.Model):
    tax_year = models.ForeignKey(PayrollTaxYear, on_delete=models.CASCADE, related_name="employer_taxes")
    province = models.CharField(max_length=2, choices=PROVINCE_CHOICES)
    name = models.CharField(max_length=120)
    rate = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal("0.0000"))
    threshold = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    applies_to_all = models.BooleanField(default=True)

    class Meta:
        unique_together = ("tax_year", "province", "name")

    def __str__(self):
        return f"{self.tax_year.year} {self.province} {self.name}"


class PMInspection(models.Model):
    """Persist preventive maintenance inspection details for a work order."""

    workorder = models.OneToOneField(
        'WorkOrder',
        on_delete=models.CASCADE,
        related_name='pm_inspection',
    )
    assignment = models.ForeignKey(
        'WorkOrderAssignment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pm_inspections',
    )
    inspector_name = models.CharField(max_length=255, blank=True)
    inspection_date = models.CharField(max_length=64, blank=True)
    scheduled_date = models.CharField(max_length=64, blank=True)
    business_snapshot = models.JSONField(default=dict, blank=True)
    customer_name = models.CharField(max_length=255, blank=True)
    location = models.TextField(blank=True)
    vehicle_snapshot = models.JSONField(default=dict, blank=True)
    checklist = models.JSONField(default=dict, blank=True)
    additional_notes = models.TextField(blank=True)
    overall_status = models.CharField(
        max_length=8,
        choices=(
            ('pass', 'Pass'),
            ('fail', 'Fail'),
        ),
        blank=True,
        default='',
        help_text="Overall inspection result selected by the mechanic.",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    def __str__(self):
        return f"PM Inspection for WorkOrder #{self.workorder_id}"


class WorkOrder(models.Model):
    # ... (Fields remain the same) ...
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mechanics = models.ManyToManyField(
        'Mechanic',
        through='WorkOrderAssignment',
        related_name='assigned_workorders',
        blank=True,
    )
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, related_name='work_orders')
    vehicle = models.ForeignKey('Vehicle', on_delete=models.SET_NULL, null=True, blank=True, related_name='work_orders')
    date_created = models.DateTimeField(auto_now_add=True)
    scheduled_date = models.DateField()
    vehicle_vin = models.CharField(max_length=17, blank=True, null=True)
    mileage = models.FloatField(blank=True, null=True)
    unit_no = models.CharField(max_length=64, blank=True, null=True)
    make_model = models.CharField(max_length=50, blank=True, null=True)
    license_plate = models.CharField(max_length=20, blank=True, null=True)
    description = models.TextField(help_text="General description of the work order", blank=True, null=True)
    road_service = models.BooleanField(default=False)
    road_location = models.CharField(max_length=255, blank=True, null=True)
    road_location_lat = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    road_location_lng = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    road_contact_phone = models.CharField(max_length=32, blank=True, null=True)
    cause = models.TextField(blank=True, null=True, help_text="Cause of the issue.")
    correction = models.TextField(blank=True, null=True, help_text="Correction performed.")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    # Mechanic-facing status (mobile app lifecycle)
    MECHANIC_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('paused', 'Paused'),
        ('travel', 'Traveling'),
        ('marked_complete', 'Marked Complete'),
    ]
    mechanic_status = models.CharField(max_length=16, choices=MECHANIC_STATUS_CHOICES, default='not_started')
    invoice = models.OneToOneField('GroupedInvoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='work_order')
    bill_to = models.CharField(max_length=100, blank=True, null=True)
    bill_to_email = models.EmailField(blank=True, null=True)
    bill_to_address = models.TextField(blank=True, null=True)
    # Mechanic time tracking and artifacts
    mechanic_started_at = models.DateTimeField(null=True, blank=True)
    mechanic_ended_at = models.DateTimeField(null=True, blank=True)
    mechanic_paused_at = models.DateTimeField(null=True, blank=True)
    mechanic_total_paused_seconds = models.PositiveIntegerField(default=0)
    mechanic_pause_reason = models.TextField(blank=True, null=True)
    # Detailed pause log: list of {start, end?, reason?, seconds?}
    mechanic_pause_log = models.JSONField(default=list, blank=True)
    # Travel time tracking
    mechanic_travel_started_at = models.DateTimeField(null=True, blank=True)
    mechanic_total_travel_seconds = models.PositiveIntegerField(default=0)
    # Mechanic completion (does not finalize business status)
    mechanic_marked_complete = models.BooleanField(default=False)
    mechanic_completed_at = models.DateTimeField(null=True, blank=True)
    signature_file = models.FileField(upload_to='pods/', null=True, blank=True)
    # Media attachments
    media_files = models.JSONField(default=list, blank=True, help_text="List of media file paths uploaded by mechanic")
    # Business completion timestamp (when status becomes completed)
    completed_at = models.DateTimeField(null=True, blank=True)

    def _invoice_sequence_from_number(self):
        invoice_number = getattr(self.invoice, "invoice_number", None)
        if not invoice_number:
            return None
        match = re.search(r"(\d+)$", str(invoice_number))
        if not match:
            return None
        return match.group(1)

    def _shared_sequence(self):
        """Return a sequence string shared across WO/Invoice labels."""
        invoice_sequence = self._invoice_sequence_from_number()
        if invoice_sequence:
            return invoice_sequence
        if not self.pk:
            return None
        return f"{self.pk:04d}"

    @property
    def workorder_number(self):
        sequence = self._shared_sequence()
        return f"WO-{sequence}" if sequence else None

    @property
    def invoice_sequence_number(self):
        if self.invoice and self.invoice.invoice_number:
            return self.invoice.invoice_number
        return None

    def __str__(self):
        return f"WorkOrder #{self.id} - {self.get_status_display()}"

    def _create_invoice_and_process_inventory(self):
        logger.info(f"Attempting invoice/inventory creation for WorkOrder #{self.id}")
        if self.invoice:
            logger.warning(f"Invoice already exists (ID: {self.invoice.id}) for WorkOrder #{self.id}. Aborting.")
            return None # Or raise an error?

        # Use a single transaction for all related creations
        with transaction.atomic():
            # 1. Create Invoice Header
            invoice = GroupedInvoice.objects.create(
                user=self.user,
                customer=self.customer,
                date=timezone.now().date(),
                vin_no=self.vehicle_vin,
                mileage=self.mileage,
                unit_no=self.unit_no,
                make_model=self.make_model,
                bill_to=self.customer.name if self.customer else self.bill_to or 'N/A',
                bill_to_address=self.customer.address if self.customer else self.bill_to_address or '',
                bill_to_email=self.customer.email if self.customer else self.bill_to_email or '',
            )
            logger.info(f"Created GroupedInvoice #{invoice.id} ({invoice.invoice_number}) for WorkOrder #{self.id}")

            # 2. Process Each WorkOrderRecord
            for record in self.records.all():
                logger.debug(
                    "Processing WO Record #%s: Prod=%s, Qty=%s, Job='%s'",
                    record.id,
                    record.product_id,
                    record.qty,
                    record.job,
                )

                # 2a. Create Invoice Line Item (IncomeRecord2)
                # Ensure IncomeRecord2 model fields match (especially Decimal types)
                try:
                    IncomeRecord2.objects.create(
                        grouped_invoice=invoice,
                        product=record.product,
                        job=record.job,
                        qty=record.qty,
                        rate=record.rate,
                        date=record.date or timezone.now().date(),
                        # Copy other relevant fields if applicable...
                    )
                except ValidationError as exc:
                    product_label = None
                    if record.product_id and record.product:
                        product_label = record.product.name
                    elif record.job:
                        product_label = record.job
                    else:
                        product_label = f"Work order line #{record.id}"

                    qty_decimal = ensure_decimal(record.qty or Decimal("0"))
                    if qty_decimal == qty_decimal.to_integral_value():
                        qty_text = format(int(qty_decimal), "d")
                    else:
                        qty_text = format(qty_decimal.quantize(Decimal("0.01")), "f")
                    shortage_message = (
                        "Not enough inventory to deduct "
                        f"{qty_text} units for '{product_label}'. "
                        "Update the product's stock level or adjust the work order before completing it."
                    )

                    raise ValidationError({"inventory": shortage_message}) from exc

                logger.debug(f"Created IncomeRecord2 for WO Record #{record.id}")

                # 2b. Inventory transactions are handled by IncomeRecord2.save()
                # Creating them here caused duplicate stock deductions.  The
                # Invoice line item creation above triggers a single inventory
                # "OUT" transaction, so we simply skip any direct inventory
                # updates in this loop.

            # 3. Finalize Invoice (assuming these methods exist)
            invoice.ensure_inventory_transactions()
            invoice.recalculate_total_amount()
            invoice.create_online_payment_link()
            PendingInvoice.objects.get_or_create(grouped_invoice=invoice)

            logger.info(f"Successfully created Invoice #{invoice.id} and processed inventory for WorkOrder #{self.id}.")
            return invoice # Return the created invoice


    def _complete_linked_maintenance_tasks(self):
        """Mark any linked maintenance tasks as completed when this work order finishes."""
        incomplete_tasks = list(
            self.maintenance_tasks.select_for_update()
            .filter(status__in=VehicleMaintenanceTask.ACTIVE_STATUSES)
        )

        if not incomplete_tasks:
            return

        completion_date = timezone.localdate()
        if self.completed_at:
            try:
                completion_date = timezone.localtime(self.completed_at).date()
            except Exception:  # pragma: no cover - fallback to localdate() if timezone conversion fails
                pass

        mileage_value = None
        if self.mileage is not None:
            try:
                mileage_value = int(round(self.mileage))
            except (TypeError, ValueError):
                logger.debug(
                    "WorkOrder #%s mileage value %s could not be converted to an integer for maintenance completion.",
                    self.id,
                    self.mileage,
                )

        for task in incomplete_tasks:
            completion_kwargs = {"work_order": self, "date": completion_date}
            if mileage_value is not None:
                completion_kwargs["mileage"] = mileage_value

            try:
                task.mark_completed(**completion_kwargs)
                logger.info(
                    "Marked maintenance task #%s ('%s') as completed from WorkOrder #%s.",
                    task.id,
                    task.title,
                    self.id,
                )
            except Exception:  # pragma: no cover - log unexpected issues but keep processing other tasks
                logger.exception(
                    "Failed to mark maintenance task #%s as completed when WorkOrder #%s was finalized.",
                    task.id,
                    self.id,
                )


    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            try:
                old_status = WorkOrder.objects.get(pk=self.pk).status
            except WorkOrder.DoesNotExist: pass

        # Determine if invoice creation should be triggered *before* saving
        # This allows the entire operation (status change + invoice/inventory)
        # to be rolled back if invoice/inventory fails.
        notify_completed = self.status == 'completed' and old_status != 'completed'
        trigger_invoice_creation = notify_completed

        if trigger_invoice_creation:
            logger.info(
                f"WorkOrder #{self.id} status changing to completed. Attempting invoice/inventory processing WITHIN save transaction..."
            )
            try:
                # Use transaction.atomic() here to wrap the status change AND the helper call
                with transaction.atomic():
                    # Save the status change *first* within this transaction
                    # Set completion timestamp
                    if not self.completed_at:
                        self.completed_at = timezone.now()
                    super().save(*args, **kwargs)  # Save the WorkOrder instance itself
                    logger.debug(f"WorkOrder #{self.id} status saved as 'completed'.")

                    # Mark any outstanding mechanic assignments as submitted
                    for assignment in self.assignments.filter(submitted=False):
                        assignment.submitted = True
                        assignment.save()

                    # Complete any linked maintenance tasks that are still open
                    self._complete_linked_maintenance_tasks()

                    # Now call the helper within the SAME transaction
                    created_invoice = self._create_invoice_and_process_inventory()

                    if created_invoice:
                        # If helper succeeds, link the invoice *without* calling save again
                        # Use update() on the queryset to avoid signals/recursion
                        WorkOrder.objects.filter(pk=self.pk).update(invoice=created_invoice)
                        self.invoice = created_invoice
                        logger.info(
                            f"Linked Invoice #{created_invoice.id} to WorkOrder #{self.id}."
                        )
                    else:
                        # Should not happen if helper raises error on failure, but log if it does
                        logger.warning(
                            f"Invoice/inventory processing returned None for completed WO #{self.id}. Invoice link missing."
                        )

            except ValidationError:
                # Bubble up validation errors (for example, inventory problems)
                # so the caller can present the message to the user.
                raise
            except DatabaseError as db_err:
                # Database errors (including TransactionManagementError) leave the
                # connection in a rollback state. Log the original error for
                # debugging and surface a user-friendly validation error so the
                # view can display feedback instead of a generic transaction error.
                logger.error(
                    "Failed to complete WorkOrder #%s due to database error: %s",
                    self.id,
                    db_err,
                    exc_info=True,
                )

                # Prefer the underlying cause when Django wraps the database
                # exception (e.g., IntegrityError -> TransactionManagementError).
                cause = getattr(db_err, "__cause__", None)
                cause_message = str(cause).strip() if cause else ""
                db_message = cause_message or str(db_err).strip()

                if not db_message or "current transaction" in db_message.lower():
                    db_message = (
                        "Unable to finalize the work order because the database "
                        "transaction could not be completed. Please review the "
                        "work order details and try again."
                    )

                raise ValidationError({"inventory": db_message}) from db_err
            except Exception as e:
                # Catch exceptions from _create_invoice_and_process_inventory
                # The atomic transaction block ensures the super().save() above is rolled back.
                logger.error(
                    f"Failed to complete WorkOrder #{self.id} due to Invoice/Inventory error: {e}. Status change rolled back."
                )
                # *** MODIFICATION: Re-raise the error ***
                # This allows the calling view (e.g., workorder_update) to catch it,
                # display a meaningful message, and prevent redirecting as if successful.
                raise e
        else:
            # If status is not changing to completed, just save normally
            # If status just became completed in a non-trigger path (safety), set completed_at
            if self.status == 'completed' and not self.completed_at:
                self.completed_at = timezone.now()
            super().save(*args, **kwargs)

        if notify_completed:
            def _send_completed_notification():
                try:
                    from .utils import notify_customer_work_completed
                    notify_customer_work_completed(self)
                except Exception:
                    logger.exception(
                        "Failed to send completion email for WorkOrder #%s",
                        self.id,
                    )
            transaction.on_commit(_send_completed_notification)

    def delete(self, *args, **kwargs):
        """Ensure any linked invoice is removed and inventory reversed."""
        with transaction.atomic():
            if self.invoice:
                self.invoice.delete()
            super(WorkOrder, self).delete(*args, **kwargs)

# ... (WorkOrderRecord and WorkOrderAssignment models remain the same as provided previously) ...

# Ensure WorkOrderRecord uses Decimal for amount
class WorkOrderRecord(models.Model):
    work_order = models.ForeignKey(WorkOrder, related_name='records', on_delete=models.CASCADE)
    product = models.ForeignKey('Product', null=True, blank=True, on_delete=models.SET_NULL)
    job = models.CharField(max_length=2000, blank=True)
    qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # *** Ensure amount is DecimalField ***
    amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=Decimal('0.00'))
    date = models.DateField(null=True, blank=True)
    ticket = models.CharField(max_length=16, null=True, blank=True)
    jobsite = models.CharField(max_length=16, null=True, blank=True)
    truck = models.CharField(max_length=16, null=True, blank=True)
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, blank=True, null=True)

    def save(self, *args, **kwargs):
        qty_val = self.qty if self.qty is not None else Decimal('0')
        rate_val = self.rate if self.rate is not None else Decimal('0')
        self.amount = (qty_val * rate_val).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)

        # Work order line items should not automatically create reusable service
        # suggestions. Service entries are now managed explicitly via the
        # dedicated service management tools instead of being inferred from
        # mechanics' free-form job descriptions on work orders.


    def __str__(self):
        description = self.job if self.job else (self.product.name if self.product else 'Unnamed Record')
        return f"{description} ({self.qty} @ {self.rate}) - ${self.amount:.2f}"


class WorkOrderAssignment(models.Model):
    workorder = models.ForeignKey('WorkOrder', related_name='assignments', on_delete=models.CASCADE)
    mechanic = models.ForeignKey('Mechanic', on_delete=models.CASCADE, related_name='assignments')
    assignment_token = models.CharField(max_length=64, unique=True, editable=False)
    submitted = models.BooleanField(default=False)
    date_assigned = models.DateTimeField(auto_now_add=True)
    date_submitted = models.DateTimeField(null=True, blank=True, editable=False) # Make editable=False
    requires_rework = models.BooleanField(default=False)
    rework_instructions = models.TextField(blank=True)
    rework_requested_at = models.DateTimeField(null=True, blank=True)

    # Internal field to track state change
    _original_submitted = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store the initial 'submitted' state when the object is loaded
        self._original_submitted = self.submitted

    def save(self, *args, **kwargs):
        # Generate token if it doesn't exist
        if not self.assignment_token:
            self.assignment_token = uuid.uuid4().hex

        # Check if 'submitted' is being changed from False to True in this save
        if self.submitted and not self._original_submitted:
            # Set date_submitted only when it transitions to True
            self.date_submitted = timezone.now()
            # Clear any pending rework state when mechanic resubmits the workorder
            self.requires_rework = False
            self.rework_requested_at = None
            self.rework_instructions = self.rework_instructions or ""
        elif not self.submitted and self._original_submitted:
            # Reset submission timestamp when business sends the workorder back
            self.date_submitted = None

        # Call the original save method
        super().save(*args, **kwargs)

        # Update the internal state tracker after save is successful
        self._original_submitted = self.submitted

    def get_link(self, request=None):
        relative_url = reverse('accounts:mechanic_fill_workorder', args=[self.assignment_token])
        if request is not None:
            return request.build_absolute_uri(relative_url)
        elif hasattr(settings, 'SITE_URL') and settings.SITE_URL:
            site_url = settings.SITE_URL.rstrip('/')
            rel_url = relative_url.lstrip('/')
            return f"{site_url}/{rel_url}"
        else:
            logger.warning("Cannot build absolute URL: request=None and settings.SITE_URL not defined.")
            return relative_url # Fallback

    def __str__(self):
        return f"Assignment for WO #{self.workorder_id} to {self.mechanic.name}"

    class Meta:
        unique_together = ('workorder', 'mechanic')


class MechanicLocationHistory(models.Model):
    mechanic = models.ForeignKey('Mechanic', related_name='location_history', on_delete=models.CASCADE)
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"Location for {self.mechanic.name} at {self.recorded_at}"


class WorkOrderUpdate(models.Model):
    work_order = models.ForeignKey('WorkOrder', related_name='updates', on_delete=models.CASCADE)
    status = models.CharField(max_length=32)
    notes = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update {self.status} for WO #{self.work_order_id}"


class WorkOrderPhoto(models.Model):
    work_order = models.ForeignKey('WorkOrder', related_name='photos', on_delete=models.CASCADE)
    photo = models.FileField(upload_to='workorder_photos/')
    caption = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)


class Vehicle(models.Model):
    """
    Stores information about a specific vehicle linked to a customer.
    """
    STATUS_ACTIVE = "active"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_OUT_OF_SERVICE = "out_of_service"
    STATUS_RETIRED = "retired"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_MAINTENANCE, "In Maintenance"),
        (STATUS_OUT_OF_SERVICE, "Out of Service"),
        (STATUS_RETIRED, "Retired"),
    ]

    customer = models.ForeignKey(
        'Customer', # Use string if Customer is defined later in the file or to avoid circular imports
        on_delete=models.CASCADE,
        related_name='vehicles',
        verbose_name="Associated Customer"
    )
    unit_number = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        verbose_name="Unit Number"
    )
    vin_number = models.CharField(
        max_length=17, # Standard VIN length
        null=True,
        blank=True,
        db_index=True, # Good for performance if you query by VIN often
        verbose_name="VIN Number"
    )
    make_model = models.CharField(
        max_length=50, # e.g., "Ford F-150", "Honda Civic"
        null=True,
        blank=True,
        verbose_name="Make and Model"
    )
    year = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Year",
    )
    license_plate = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="License Plate",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        blank=True,
        verbose_name="Status",
    )
    start_date_in_service = models.DateField(
        null=True,
        blank=True,
        verbose_name="Start Date In Service",
    )
    assigned_to = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Department/Assigned To",
    )
    current_mileage = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Latest recorded mileage for the vehicle",
        verbose_name="Current Mileage",
    )
    # You can add other vehicle-specific fields here if needed in the future
    # e.g., year = models.PositiveIntegerField(null=True, blank=True)
    # color = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        verbose_name = "Vehicle"
        verbose_name_plural = "Vehicles"
        ordering = ['customer', 'vin_number'] # Default ordering for queries
        constraints = [
            # VIN uniqueness should not be global: different businesses can service the same vehicle.
            # Enforce uniqueness per customer (case-insensitive) to prevent accidental duplicates within an account.
            models.UniqueConstraint(
                Lower("vin_number"),
                "customer",
                name="unique_vehicle_vin_per_customer",
                condition=Q(vin_number__isnull=False) & ~Q(vin_number=""),
            )
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and not self.start_date_in_service:
            self.start_date_in_service = timezone.localdate()
        super().save(*args, **kwargs)

    def __str__(self):
        parts = []
        if self.vin_number: # Ensure vin_number is not None before adding
            parts.append(self.vin_number)
        if self.make_model:
            parts.append(self.make_model)
        if self.unit_number:
            parts.append(f"(Unit: {self.unit_number})")

        customer_name = self.customer.name if self.customer else 'N/A'
        return " - ".join(parts) + f" [{customer_name}]"


class VehicleServicePortalOverride(models.Model):
    """Customer-editable service dates shown in the portal vehicle list."""

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='service_portal_overrides',
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='vehicle_portal_overrides',
    )
    last_service_date = models.DateField(null=True, blank=True)
    last_service_mileage = models.PositiveIntegerField(null=True, blank=True)
    next_service_date = models.DateField(null=True, blank=True)
    next_service_mileage = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['vehicle', 'service'],
                name='unique_vehicle_service_portal_override',
            ),
        ]

    def __str__(self):
        return f"{self.vehicle_id} · {self.service_id}"


class VehicleMaintenanceTask(models.Model):
    """Track scheduled and completed maintenance for customer vehicles."""

    STATUS_PLANNED = 'planned'
    STATUS_SCHEDULED = 'scheduled'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PLANNED, 'Planned'),
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PRIORITY_LOW = 'low'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_HIGH = 'high'

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
    ]

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='maintenance_tasks',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='maintenance_tasks',
    )
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    due_mileage = models.PositiveIntegerField(null=True, blank=True)
    mileage_interval = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Mileage interval for recurring maintenance reminders.",
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED, db_index=True)
    work_order = models.ForeignKey(
        'WorkOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_tasks',
    )
    grouped_invoice = models.ForeignKey(
        'GroupedInvoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_tasks',
    )
    completed_date = models.DateField(null=True, blank=True)
    actual_mileage = models.PositiveIntegerField(null=True, blank=True)
    completion_notes = models.TextField(blank=True)
    last_reminder_sent = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last maintenance reminder email sent for this task.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    ACTIVE_STATUSES = {STATUS_PLANNED, STATUS_SCHEDULED, STATUS_IN_PROGRESS}

    DEFAULT_MILEAGE_INTERVALS = [
        3000,
        5000,
        7500,
        10000,
        12000,
        15000,
        20000,
        25000,
        30000,
        35000,
        40000,
        45000,
        50000,
        60000,
        75000,
        90000,
        100000,
    ]

    class Meta:
        verbose_name = "Vehicle Maintenance Task"
        verbose_name_plural = "Vehicle Maintenance Tasks"
        ordering = ['status', 'due_date', 'priority', 'title']

    def __str__(self):
        return f"{self.title} - {self.vehicle}"

    @property
    def is_overdue(self):
        if self.status in {self.STATUS_COMPLETED, self.STATUS_CANCELLED}:
            return False
        return bool(self.due_date and self.due_date < timezone.localdate())

    @property
    def mileage_interval_display(self):
        if not self.mileage_interval:
            return None
        return f"Every {self.mileage_interval:,} km"

    @property
    def next_due_mileage(self):
        if not self.mileage_interval:
            return None
        base_mileage = None
        if getattr(self, "due_mileage", None):
            base_mileage = self.due_mileage
        elif getattr(self, "vehicle", None) is not None:
            base_mileage = self.vehicle.current_mileage
        if base_mileage is None and getattr(self, "actual_mileage", None) is not None:
            base_mileage = self.actual_mileage
        if base_mileage is None:
            return None
        return base_mileage + self.mileage_interval

    @classmethod
    def active_statuses(cls):
        return list(cls.ACTIVE_STATUSES)

    @classmethod
    def mileage_interval_choices(cls):
        return [(value, f"Every {value:,} km") for value in cls.DEFAULT_MILEAGE_INTERVALS]

    def mark_completed(self, *, date=None, mileage=None, notes=None, work_order=None):
        """Convenience helper to mark the task completed."""
        self.status = self.STATUS_COMPLETED
        self.completed_date = date or timezone.localdate()
        if mileage is not None:
            self.actual_mileage = mileage
        if notes is not None:
            self.completion_notes = notes
        if work_order is not None:
            self.work_order = work_order
        self.save()

class JobHistory(models.Model):
    """
    Records a history of jobs or services performed on a vehicle,
    derived from IncomeRecord2.
    """
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='job_history',
        verbose_name="Associated Vehicle"
    )
    # Link to the original GroupedInvoice for context
    invoice = models.ForeignKey(
        'GroupedInvoice', # Use string if GroupedInvoice is defined later or to avoid circular imports
        on_delete=models.SET_NULL,
        null=True,
        blank=True, # A job history might exist even if the invoice is later deleted
        related_name='job_history_entries', # e.g., invoice.job_history_entries.all()
        verbose_name="Originating Invoice"
    )
    # Direct link to the IncomeRecord2 line item that this job history entry represents
    source_income_record = models.OneToOneField(
        'IncomeRecord2', # Use string for IncomeRecord2
        on_delete=models.SET_NULL, # If IncomeRecord2 is deleted, keep the job history, nullify link.
                                   # Or models.CASCADE if JobHistory should be deleted with IncomeRecord2.
        null=True,
        blank=True, # Should ideally always have a source, but SET_NULL requires null=True.
        related_name='job_history_entry',
        verbose_name="Source Invoice Line Item"
    )
    job_date = models.DateField(
        verbose_name="Date of Job/Service",
        help_text="Date the specific job was performed."
    )
    description = models.TextField(
        verbose_name="Job Description",
        help_text="Description of the service or parts used."
    )
    # Cost breakdown from IncomeRecord2
    # IncomeRecord2.amount is pre-tax. We'll store it as 'service_cost' or 'labor_cost'.
    # For simplicity, let's call it 'service_cost' as 'job' or 'product' can imply either labor or parts.
    service_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Pre-tax Service/Parts Cost",
        help_text="Corresponds to the 'amount' field from the invoice line item."
    )
    # parts_cost and labor_cost can be added if you later have a way to differentiate them.
    # For now, service_cost holds the primary pre-tax value from IncomeRecord2.amount.
    # parts_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # labor_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    tax_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Tax Amount on this Job",
        help_text="Corresponds to the 'tax_collected' field from the invoice line item."
    )
    total_job_cost = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Total Cost for this Job (including tax)",
        editable=False # Calculated in save method
    )
    notes = models.TextField(
        blank=True, null=True,
        verbose_name="Additional Notes (e.g., ticket, jobsite, truck, driver)"
    )

    class Meta:
        verbose_name = "Job History Record"
        verbose_name_plural = "Job History Records"
        ordering = ['-job_date', 'vehicle'] # Show newest jobs first

    def save(self, *args, **kwargs):
        # Auto-calculate total_job_cost
        self.total_job_cost = (self.service_cost + self.tax_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def __str__(self):
        vehicle_info = self.vehicle.vin_number if self.vehicle else 'N/A Vehicle'
        return f"Job on {vehicle_info} - {self.job_date} - {self.description[:50]}..."

class ReminderLog(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='reminder_logs')
    sent_at = models.DateTimeField(default=timezone.now) # Records the timestamp of when the reminder was sent
    # You could add more fields here if needed, e.g., which invoices were included,
    # or the sequence number, though sequence can be derived.

    class Meta:
        ordering = ['-sent_at'] # Orders logs by most recent first

    def __str__(self):
        return f"Reminder for {self.customer.email} sent at {self.sent_at.strftime('%Y-%m-%d %H:%M')}"


class InvoiceActivity(models.Model):
    EVENT_EMAIL_SENT = "email_sent"
    EVENT_EMAIL_OPENED = "email_opened"
    EVENT_VIEWED = "viewed"
    EVENT_CHOICES = [
        (EVENT_EMAIL_SENT, "Email sent"),
        (EVENT_EMAIL_OPENED, "Email opened"),
        (EVENT_VIEWED, "Viewed"),
    ]

    invoice = models.ForeignKey(
        GroupedInvoice,
        on_delete=models.CASCADE,
        related_name="activity_entries",
    )
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_activities",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        label = dict(self.EVENT_CHOICES).get(self.event_type, self.event_type)
        return f"Invoice {self.invoice_id} - {label}"


class FleetVehicle(models.Model):
    """A vehicle owned by a contractor for internal fleet management."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="fleet_vehicles",
    )
    make = models.CharField(max_length=50, null=True, blank=True)
    model = models.CharField(max_length=50, null=True, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    vin_number = models.CharField(max_length=17, unique=True)
    license_plate = models.CharField(max_length=15, null=True, blank=True)
    truck_number = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "Fleet Vehicle"
        verbose_name_plural = "Fleet Vehicles"
        ordering = ["make", "model", "vin_number"]

    def __str__(self):
        parts = [
            f"#{self.truck_number}" if self.truck_number else None,
            str(self.year) if self.year else None,
            self.make,
            self.model,
            self.license_plate or self.vin_number,
        ]
        return " ".join(p for p in parts if p)


class MaintenanceRecord(models.Model):
    """Maintenance log entry for a contractor's fleet vehicle."""
    vehicle = models.ForeignKey(
        FleetVehicle,
        related_name="maintenance_records",
        on_delete=models.CASCADE,
    )
    date = models.DateField(default=timezone.now)
    description = models.TextField()
    odometer_reading = models.PositiveIntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    next_due = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Maintenance Record"
        verbose_name_plural = "Maintenance Records"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.vehicle} - {self.date} - {self.description[:50]}"


# ============================================
# TRANSPORT INDUSTRY MODELS
# ============================================

class TransportProfile(models.Model):
    """Profile for transport companies using smart-invoices"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='transport_profile')
    company_name = models.CharField(max_length=200)
    dot_number = models.CharField(max_length=50, blank=True, null=True, help_text="DOT Number")
    mc_number = models.CharField(max_length=50, blank=True, null=True, help_text="MC Number")
    scac_code = models.CharField(max_length=10, blank=True, null=True, help_text="SCAC Code")
    operating_authority = models.CharField(max_length=100, blank=True, null=True)
    insurance_company = models.CharField(max_length=200, blank=True, null=True)
    insurance_policy = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.company_name} - {self.user.username}"

class TransportCustomer(models.Model):
    """Enhanced customer model for transport operations"""
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='transport_data')
    
    customer_type = models.CharField(max_length=20, choices=[
        ('shipper', 'Shipper'),
        ('consignee', 'Consignee'),
        ('broker', 'Broker'),
        ('both', 'Shipper/Consignee')
    ], default='shipper')
    
    dispatch_phone = models.CharField(max_length=20, blank=True, null=True)
    dispatch_email = models.EmailField(blank=True, null=True)
    billing_contact = models.CharField(max_length=100, blank=True, null=True)
    duns_number = models.CharField(max_length=20, blank=True, null=True)
    freight_class = models.CharField(max_length=10, blank=True, null=True)
    special_instructions = models.TextField(blank=True, null=True)
    payment_terms_days = models.IntegerField(default=30)
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Transport: {self.customer.name}"

class TransportVehicle(models.Model):
    """Vehicle information for transport operations"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_vehicles')
    unit_number = models.CharField(max_length=64)
    vin = models.CharField(max_length=17, blank=True, null=True)
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    year = models.IntegerField()
    
    vehicle_type = models.CharField(max_length=30, choices=[
        ('truck', 'Truck'),
        ('trailer', 'Trailer'),
        ('van', 'Van'),
        ('flatbed', 'Flatbed'),
        ('tanker', 'Tanker'),
        ('refrigerated', 'Refrigerated'),
    ])
    
    max_weight = models.DecimalField(max_digits=10, decimal_places=2)
    max_length = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    max_width = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    max_height = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    
    license_plate = models.CharField(max_length=20, blank=True, null=True)
    registration_state = models.CharField(max_length=2, blank=True, null=True)
    insurance_policy = models.CharField(max_length=100, blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('maintenance', 'In Maintenance'),
        ('out_of_service', 'Out of Service'),
        ('retired', 'Retired')
    ], default='active')
    
    current_location = models.CharField(max_length=200, blank=True, null=True)
    last_maintenance = models.DateField(blank=True, null=True)
    next_maintenance = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'unit_number']
    
    def __str__(self):
        return f"{self.unit_number} - {self.make} {self.model}"

class TransportDriver(models.Model):
    """Driver information for transport operations"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_drivers')
    employee_id = models.CharField(max_length=50, blank=True, null=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField()
    
    license_number = models.CharField(max_length=50)
    license_state = models.CharField(max_length=2)
    license_class = models.CharField(max_length=10, default='CDL-A')
    license_expiry = models.DateField()
    
    hire_date = models.DateField()
    employment_status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('terminated', 'Terminated'),
        ('on_leave', 'On Leave')
    ], default='active')
    
    pay_type = models.CharField(max_length=20, choices=[
        ('per_mile', 'Per Mile'),
        ('percentage', 'Percentage'),
        ('hourly', 'Hourly'),
        ('salary', 'Salary'),
        ('per_load', 'Per Load')
    ], default='per_mile')
    pay_rate = models.DecimalField(max_digits=8, decimal_places=4)
    
    medical_expiry = models.DateField(blank=True, null=True)
    drug_test_date = models.DateField(blank=True, null=True)
    background_check_date = models.DateField(blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'employee_id']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class TransportTrip(models.Model):
    """Trip/Load information for transport operations"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_trips')
    trip_number = models.CharField(max_length=50, unique=True)
    load_number = models.CharField(max_length=50, blank=True, null=True)
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='transport_trips')
    driver = models.ForeignKey(TransportDriver, on_delete=models.SET_NULL, null=True, blank=True)
    vehicle = models.ForeignKey(TransportVehicle, on_delete=models.SET_NULL, null=True, blank=True)
    
    origin_address = models.TextField()
    origin_city = models.CharField(max_length=100)
    origin_state = models.CharField(max_length=2)
    origin_zip = models.CharField(max_length=10)
    
    destination_address = models.TextField()
    destination_city = models.CharField(max_length=100)
    destination_state = models.CharField(max_length=2)
    destination_zip = models.CharField(max_length=10)
    
    pickup_date = models.DateTimeField()
    delivery_date = models.DateTimeField()
    actual_pickup = models.DateTimeField(blank=True, null=True)
    actual_delivery = models.DateTimeField(blank=True, null=True)
    
    commodity = models.CharField(max_length=200)
    weight = models.DecimalField(max_digits=10, decimal_places=2)
    pieces = models.IntegerField(default=1)
    freight_class = models.CharField(max_length=10, blank=True, null=True)
    
    total_rate = models.DecimalField(max_digits=10, decimal_places=2)
    fuel_surcharge = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    accessorial_charges = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    status = models.CharField(max_length=20, choices=[
        ('dispatched', 'Dispatched'),
        ('en_route_pickup', 'En Route to Pickup'),
        ('at_pickup', 'At Pickup'),
        ('loaded', 'Loaded'),
        ('en_route_delivery', 'En Route to Delivery'),
        ('at_delivery', 'At Delivery'),
        ('delivered', 'Delivered'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], default='dispatched')
    
    total_miles = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    driving_hours = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    
    bol_number = models.CharField(max_length=50, blank=True, null=True)
    po_number = models.CharField(max_length=50, blank=True, null=True)
    pro_number = models.CharField(max_length=50, blank=True, null=True)
    
    special_instructions = models.TextField(blank=True, null=True)
    driver_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Trip {self.trip_number} - {self.customer.name}"
    
    @property
    def total_amount(self):
        return self.total_rate + self.fuel_surcharge + self.accessorial_charges

class TransportInvoice(models.Model):
    """Enhanced invoice model for transport operations"""
    grouped_invoice = models.OneToOneField(GroupedInvoice, on_delete=models.CASCADE, related_name='transport_data')
    trips = models.ManyToManyField(TransportTrip, related_name='invoices')
    
    billing_type = models.CharField(max_length=20, choices=[
        ('per_load', 'Per Load'),
        ('consolidated', 'Consolidated'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly')
    ], default='per_load')
    
    total_loads = models.IntegerField(default=0, editable=False)
    total_miles = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)
    total_weight = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    
    line_haul = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fuel_surcharge = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    accessorial_total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        if self.pk:
            trips = self.trips.all()
            self.total_loads = trips.count()
            self.total_miles = sum(trip.total_miles or 0 for trip in trips)
            self.total_weight = sum(trip.weight or 0 for trip in trips)
            self.line_haul = sum(trip.total_rate or 0 for trip in trips)
            self.fuel_surcharge = sum(trip.fuel_surcharge or 0 for trip in trips)
            self.accessorial_total = sum(trip.accessorial_charges or 0 for trip in trips)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Transport Invoice: {self.grouped_invoice.invoice_number}"


# ===== Transport domain models =====

RATE_TYPE_CHOICES = (
    ("flat", "Flat"),
    ("hourly", "Hourly"),
    ("per_mile", "Per Mile"),
    ("per_km", "Per KM"),
    ("per_ton", "Per Ton"),
    ("per_load", "Per Load"),
)


class TransportOrder(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transport_orders")
    customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True,
        related_name='transport_orders',
    )
    order_number = models.CharField(max_length=32)
    reference_no = models.CharField(max_length=64, blank=True, null=True)
    origin = models.CharField(max_length=255, blank=True, null=True)
    destination = models.CharField(max_length=255, blank=True, null=True)
    commodity = models.CharField(max_length=255, blank=True, null=True)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    volume_cbm = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    rate_type = models.CharField(max_length=16, choices=RATE_TYPE_CHOICES, default="flat")
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    planned_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    fuel_surcharge_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
    )
    other_surcharges = models.TextField(blank=True, null=True)
    pickup_window_start = models.DateTimeField(blank=True, null=True)
    pickup_window_end = models.DateTimeField(blank=True, null=True)
    delivery_window_start = models.DateTimeField(blank=True, null=True)
    delivery_window_end = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=16,
        default='active',
        choices=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
    )
    invoice_on_trip_completion = models.BooleanField(default=True)
    linked_invoice = models.ForeignKey(
        'GroupedInvoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transport_orders',
    )
    attachment = models.FileField(upload_to='order_attachments/', blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'order_number'], name='uniq_order_per_user')
        ]

    def __str__(self):
        return f"Order {self.order_number} ({self.customer})"


class Trip(models.Model):
    order = models.ForeignKey(TransportOrder, on_delete=models.CASCADE, related_name='trips')
    date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=16,
        default='planned',
        choices=[
            ('planned', 'Planned'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
    )
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, null=True, blank=True)
    vehicle = models.ForeignKey('FleetVehicle', on_delete=models.SET_NULL, null=True, blank=True)
    odometer_start = models.PositiveIntegerField(blank=True, null=True)
    odometer_end = models.PositiveIntegerField(blank=True, null=True)
    distance = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    hours_worked = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    start_at = models.DateTimeField(blank=True, null=True)
    end_at = models.DateTimeField(blank=True, null=True)
    origin_override = models.CharField(max_length=255, blank=True, null=True)
    destination_override = models.CharField(max_length=255, blank=True, null=True)
    route_summary = models.TextField(blank=True, null=True)

    # Billing snapshots at completion
    revenue_rate_type_snapshot = models.CharField(
        max_length=16,
        choices=RATE_TYPE_CHOICES,
        blank=True,
        null=True,
    )
    revenue_rate_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    revenue_qty_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    computed_amount_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    computed_tax_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )

    pod_file = models.FileField(upload_to='pods/', blank=True, null=True)
    other_docs = models.FileField(upload_to='trip_docs/', blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    invoice = models.ForeignKey(
        'GroupedInvoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trips',
    )

    # internal state tracking
    _original_status = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status

    def __str__(self):
        return f"Trip #{self.pk or 'new'} - {self.order.order_number} ({self.get_status_display()})"

    def _get_qty_for_rate_type(self) -> Decimal:
        rt = self.order.rate_type
        if rt == 'flat':
            return Decimal('1.00')
        if rt == 'hourly':
            return (self.hours_worked or Decimal('0'))
        if rt in ('per_mile', 'per_km'):
            if self.distance is not None:
                return Decimal(str(self.distance))
            if (
                self.odometer_start is not None and
                self.odometer_end is not None and
                self.odometer_end >= self.odometer_start
            ):
                return Decimal(str(self.odometer_end - self.odometer_start))
            return Decimal('0')
        if rt in ('per_ton', 'per_load'):
            return self.order.planned_quantity or Decimal('0')
        return Decimal('0')

    def _ensure_distance(self):
        if (
            self.distance is None and
            self.odometer_start is not None and
            self.odometer_end is not None and
            self.odometer_end >= self.odometer_start
        ):
            self.distance = Decimal(str(self.odometer_end - self.odometer_start))

    def _create_or_append_invoice(self):
        order = self.order
        user = order.user
        customer = order.customer

        invoice = GroupedInvoice.objects.create(
            user=user,
            customer=customer,
            date=timezone.now().date(),
            bill_to=customer.name if customer else None,
            bill_to_email=customer.email if customer else None,
            bill_to_address=customer.address if customer else None,
        )

        qty = self._get_qty_for_rate_type()
        rate = order.rate
        amount = (qty * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        job_desc = f"Transport: Order {order.order_number} Trip {self.pk or ''} {order.origin or ''} -> {order.destination or ''}".strip()
        IncomeRecord2.objects.create(
            grouped_invoice=invoice,
            job=job_desc,
            qty=qty,
            rate=rate,
            driver=self.driver,
            date=self.date,
        )

        invoice.recalculate_total_amount()
        PendingInvoice.objects.get_or_create(grouped_invoice=invoice)

        return invoice, qty, rate, amount

    def _create_driver_settlement_activity(self, qty: Decimal, rate_for_driver: Decimal, job_desc: str):
        DriverSettlementActivity.objects.create(
            settlement=DriverSettlementStatement.objects.create(
                user=self.order.user,
                driver=self.driver,
                date_from=self.date,
                date_to=self.date,
            ),
            job=job_desc,
            qty=qty,
            rate=rate_for_driver,
            date=self.date,
            ticket=str(self.pk or ''),
            jobsite=self.order.destination or '',
            truck=(self.vehicle.truck_number if self.vehicle else None) or '',
        )

    def save(self, *args, **kwargs):
        self._ensure_distance()

        status_changed_to_completed = (self._original_status != 'completed' and self.status == 'completed')

        if status_changed_to_completed:
            if not self.driver or not self.vehicle:
                raise ValidationError("Driver and Vehicle are required to complete a trip.")
            if (
                self.odometer_start is not None and
                self.odometer_end is not None and
                self.odometer_end < self.odometer_start
            ):
                raise ValidationError("Odometer end must be greater than or equal to start.")

        super().save(*args, **kwargs)

        if status_changed_to_completed and self.invoice is None:
            with transaction.atomic():
                invoice, qty, rate, amount = self._create_or_append_invoice()

                self.revenue_rate_type_snapshot = self.order.rate_type
                self.revenue_rate_snapshot = rate
                self.revenue_qty_snapshot = qty
                self.computed_amount_snapshot = amount
                self.invoice = invoice
                self.completed_at = timezone.now()
                super().save(update_fields=[
                    'revenue_rate_type_snapshot', 'revenue_rate_snapshot', 'revenue_qty_snapshot',
                    'computed_amount_snapshot', 'invoice', 'completed_at'
                ])

                if getattr(self.order.user.profile, 'occupation', None) != 'transport':
                    driver_rate = self.driver.pay_rate or Decimal('0.00')
                    job_desc = f"Transport: Order {self.order.order_number} Trip {self.pk}"
                    self._create_driver_settlement_activity(qty, driver_rate, job_desc)


class QuickBooksConnection(models.Model):
    """Stores a single QuickBooks company (realm) connection per user."""
    ENV_CHOICES = (
        ("sandbox", "Sandbox"),
        ("production", "Production"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="qbo_connection")
    realm_id = models.TextField()

    access_token = models.TextField()
    refresh_token = models.TextField()
    access_token_expires_at = models.DateTimeField()
    refresh_token_expires_at = models.DateTimeField()

    env = models.CharField(max_length=16, choices=ENV_CHOICES, default="sandbox")
    last_sync_at = models.DateTimeField(null=True, blank=True)

    # --- Sync toggles ---
    sync_customers_on_create = models.BooleanField(default=False)
    sync_invoices_on_create = models.BooleanField(default=False)
    sync_estimates_on_create = models.BooleanField(default=False)
    sync_payments_on_create = models.BooleanField(default=False)
    sync_expenses_on_create = models.BooleanField(default=False)
    sync_invoice_on_workorder_completion = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "QuickBooks Connection"
        verbose_name_plural = "QuickBooks Connections"

    def __str__(self):
        return f"QBO {self.env} realm {self.realm_id_plain or '[unset]'} for {self.user.username}"

    @staticmethod
    def _get_cipher():
        key = getattr(settings, "QBO_TOKEN_ENC_KEY", None)
        if not key:
            return None
        try:
            return Fernet(key)
        except Exception:
            return None

    @property
    def access_token_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.access_token
        try:
            return cipher.decrypt(self.access_token.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @access_token_plain.setter
    def access_token_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.access_token = value
        else:
            self.access_token = cipher.encrypt(value.encode()).decode()

    @property
    def refresh_token_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.refresh_token
        try:
            return cipher.decrypt(self.refresh_token.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @refresh_token_plain.setter
    def refresh_token_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.refresh_token = value
        else:
            self.refresh_token = cipher.encrypt(value.encode()).decode()

    @property
    def realm_id_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.realm_id
        try:
            return cipher.decrypt(self.realm_id.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @realm_id_plain.setter
    def realm_id_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.realm_id = value
        else:
            self.realm_id = cipher.encrypt(value.encode()).decode()

    def save(self, *args, **kwargs):
        if self.sync_invoice_on_workorder_completion and not self.sync_invoices_on_create:
            self.sync_invoices_on_create = True
        super().save(*args, **kwargs)


class CloverConnection(models.Model):
    """Stores Clover merchant tokens per user."""

    ENV_CHOICES = (
        ("sandbox", "Sandbox"),
        ("production", "Production"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="clover_connection")
    merchant_id = models.CharField(max_length=64, unique=True)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_type = models.CharField(max_length=32, blank=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)
    env = models.CharField(max_length=16, choices=ENV_CHOICES, default="sandbox")
    sync_pos_payments = models.BooleanField(default=True)
    sync_online_payments = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Clover Connection"
        verbose_name_plural = "Clover Connections"

    def __str__(self):
        return f"Clover {self.env} {self.merchant_id} for {self.user.username}"

    @staticmethod
    def _get_cipher():
        key = getattr(settings, "CLOVER_TOKEN_ENC_KEY", None)
        if not key:
            return None
        try:
            return Fernet(key)
        except Exception:
            return None

    @property
    def access_token_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.access_token
        try:
            return cipher.decrypt(self.access_token.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @access_token_plain.setter
    def access_token_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.access_token = value
        else:
            self.access_token = cipher.encrypt(value.encode()).decode()

    @property
    def refresh_token_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.refresh_token or ""
        try:
            return cipher.decrypt(self.refresh_token.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @refresh_token_plain.setter
    def refresh_token_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.refresh_token = value
        else:
            self.refresh_token = cipher.encrypt(value.encode()).decode()

    @property
    def is_configured(self) -> bool:
        return bool(self.merchant_id and self.access_token_plain)


class BankingIntegrationSettings(models.Model):
    """Stores banking integration settings per user."""

    PROVIDER_FLINKS = "flinks"
    PROVIDER_CHOICES = (
        (PROVIDER_FLINKS, "Flinks"),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="banking_settings",
    )
    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_FLINKS,
    )
    enabled = models.BooleanField(default=False)
    auto_sync_enabled = models.BooleanField(default=True)
    require_review = models.BooleanField(
        default=True,
        help_text="Queue transactions for review before creating expenses.",
    )
    last_synced_at = models.DateTimeField(blank=True, null=True)
    last_sync_status = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Banking Integration"
        verbose_name_plural = "Banking Integrations"

    def __str__(self) -> str:
        return f"Banking settings for {self.user}"


class BankConnection(models.Model):
    """Stores connected bank accounts for transaction syncing."""

    ENV_CHOICES = (
        ("sandbox", "Sandbox"),
        ("production", "Production"),
    )
    STATUS_CONNECTED = "connected"
    STATUS_DISCONNECTED = "disconnected"
    STATUS_ERROR = "error"
    STATUS_CHOICES = (
        (STATUS_CONNECTED, "Connected"),
        (STATUS_DISCONNECTED, "Disconnected"),
        (STATUS_ERROR, "Error"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bank_connections")
    provider = models.CharField(
        max_length=20,
        choices=BankingIntegrationSettings.PROVIDER_CHOICES,
        default=BankingIntegrationSettings.PROVIDER_FLINKS,
    )
    connection_id = models.CharField(max_length=128)
    institution_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONNECTED)
    access_token = models.TextField(blank=True, null=True)
    refresh_token = models.TextField(blank=True, null=True)
    env = models.CharField(max_length=16, choices=ENV_CHOICES, default="production")
    last_sync_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "provider", "connection_id")
        verbose_name = "Bank Connection"
        verbose_name_plural = "Bank Connections"

    def __str__(self) -> str:
        name = self.institution_name or self.connection_id
        return f"{self.provider} {name} for {self.user.username}"

    @staticmethod
    def _get_cipher():
        key = getattr(settings, "BANKING_TOKEN_ENC_KEY", None)
        if not key:
            return None
        try:
            return Fernet(key)
        except Exception:
            return None

    @property
    def access_token_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.access_token or ""
        try:
            return cipher.decrypt(self.access_token.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @access_token_plain.setter
    def access_token_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.access_token = value
        else:
            self.access_token = cipher.encrypt(value.encode()).decode()

    @property
    def refresh_token_plain(self) -> str:
        cipher = self._get_cipher()
        if not cipher:
            return self.refresh_token or ""
        try:
            return cipher.decrypt(self.refresh_token.encode()).decode()
        except (InvalidToken, Exception):
            return ""

    @refresh_token_plain.setter
    def refresh_token_plain(self, value: str):
        cipher = self._get_cipher()
        if not cipher:
            self.refresh_token = value
        else:
            self.refresh_token = cipher.encrypt(value.encode()).decode()


class BankTransaction(models.Model):
    """Stores transactions imported from connected bank accounts."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_IGNORED = "ignored"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_IGNORED, "Ignored"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bank_transactions")
    connection = models.ForeignKey(
        BankConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    provider = models.CharField(
        max_length=20,
        choices=BankingIntegrationSettings.PROVIDER_CHOICES,
        default=BankingIntegrationSettings.PROVIDER_FLINKS,
    )
    external_id = models.CharField(max_length=128)
    account_id = models.CharField(max_length=128, blank=True)
    account_name = models.CharField(max_length=120, blank=True)
    institution_name = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="CAD")
    description = models.TextField(blank=True)
    merchant_name = models.CharField(max_length=120, blank=True)
    posted_at = models.DateField(blank=True, null=True)
    authorized_at = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    linked_expense = models.ForeignKey(
        "MechExpense",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transactions",
    )
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "provider", "external_id")
        indexes = [
            models.Index(fields=["user", "status", "posted_at"]),
        ]
        verbose_name = "Bank Transaction"
        verbose_name_plural = "Bank Transactions"

    def __str__(self) -> str:
        label = self.merchant_name or self.description or "Bank transaction"
        return f"{self.user.username} - {label}"


class QuickBooksImportMap(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="qbo_import_maps")
    object_type = models.CharField(max_length=32)
    qbo_id = models.CharField(max_length=64)
    local_app_label = models.CharField(max_length=64)
    local_model_name = models.CharField(max_length=64)
    local_object_id = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "object_type", "qbo_id")
        indexes = [
            models.Index(fields=["user", "object_type", "qbo_id"]),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.object_type}:{self.qbo_id} -> {self.local_app_label}.{self.local_model_name}#{self.local_object_id}"


# ============================================
# PUBLIC-FACING TRANSPORT FEATURES
# ============================================


class QuickBooksSettings(models.Model):
    """Stores credentials and sync preferences for QuickBooks integrations."""

    ENVIRONMENT_SANDBOX = "sandbox"
    ENVIRONMENT_PRODUCTION = "production"
    ENVIRONMENT_CHOICES = (
        (ENVIRONMENT_SANDBOX, "Sandbox"),
        (ENVIRONMENT_PRODUCTION, "Production"),
    )

    INTEGRATION_ONLINE = "online"
    INTEGRATION_DESKTOP = "desktop"
    INTEGRATION_CHOICES = (
        (INTEGRATION_ONLINE, "QuickBooks Online"),
        (INTEGRATION_DESKTOP, "QuickBooks Desktop"),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="quickbooks_settings",
    )
    integration_type = models.CharField(
        max_length=20,
        choices=INTEGRATION_CHOICES,
        default=INTEGRATION_ONLINE,
    )
    client_id = models.CharField(max_length=200, blank=True)
    client_secret = models.CharField(max_length=200, blank=True)
    realm_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="QuickBooks company (realm) identifier.",
    )
    redirect_uri = models.URLField(
        blank=True,
        help_text="OAuth redirect URI registered with your QuickBooks app.",
    )
    environment = models.CharField(
        max_length=12,
        choices=ENVIRONMENT_CHOICES,
        default=ENVIRONMENT_SANDBOX,
    )
    refresh_token = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Paste the refresh token from the QuickBooks developer portal.",
    )
    access_token = models.CharField(max_length=500, blank=True, null=True)
    access_token_expires_at = models.DateTimeField(blank=True, null=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    last_sync_status = models.CharField(max_length=255, blank=True, null=True)
    auto_sync_enabled = models.BooleanField(default=False)
    desktop_company_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Company name exactly as it appears in QuickBooks Desktop.",
    )
    desktop_last_exported_at = models.DateTimeField(blank=True, null=True)
    desktop_last_export_filename = models.CharField(max_length=255, blank=True)
    desktop_last_imported_at = models.DateTimeField(blank=True, null=True)
    desktop_last_import_filename = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "QuickBooks Integration"
        verbose_name_plural = "QuickBooks Integrations"

    def __str__(self) -> str:
        return f"QuickBooks settings for {self.user}"  # pragma: no cover - human readable representation

    @property
    def is_configured(self) -> bool:
        if self.integration_type == self.INTEGRATION_DESKTOP:
            return bool(self.desktop_company_name)

        return all([
            self.client_id,
            self.client_secret,
            self.realm_id,
            self.refresh_token,
        ])

    def has_valid_access_token(self) -> bool:
        if self.integration_type == self.INTEGRATION_DESKTOP:
            return True
        if not self.access_token or not self.access_token_expires_at:
            return False
        return self.access_token_expires_at > timezone.now()

    def mark_synced(self, status_message: str | None = None) -> None:
        """Record the most recent synchronization timestamp and optional status."""

        self.last_synced_at = timezone.now()
        self.last_sync_status = status_message or ""
        self.save(update_fields=['last_synced_at', 'last_sync_status', 'updated_at'])

    def clear_cached_tokens(self) -> None:
        """Force the next sync to refresh tokens."""

        if self.integration_type == self.INTEGRATION_DESKTOP:
            return

        self.access_token = None
        self.access_token_expires_at = None
        self.save(update_fields=['access_token', 'access_token_expires_at', 'updated_at'])


class BusinessBookingSettings(models.Model):
    """Configurable business hours used by the public booking form."""

    start_time = models.TimeField(
        default=datetime.time(hour=9, minute=0),
        help_text="Opening time for online bookings.",
    )
    end_time = models.TimeField(
        default=datetime.time(hour=17, minute=0),
        help_text="Closing time for online bookings.",
    )
    slot_interval_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Length of each appointment slot in minutes.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Booking business setting"
        verbose_name_plural = "Booking business settings"

    def clean(self):
        super().clean()
        if self.end_time <= self.start_time:
            raise ValidationError("Closing time must be after opening time.")
        if self.slot_interval_minutes <= 0:
            raise ValidationError("Slot interval must be a positive number of minutes.")

    @classmethod
    def get_solo(cls):
        """Return the singleton settings object, creating it with defaults when missing."""

        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class BusinessHoliday(models.Model):
    """Specific days the shop is closed along with an optional public reason."""

    date = models.DateField(unique=True)
    reason = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]

    def __str__(self) -> str:
        label = self.reason or "Holiday"
        return f"{label} – {self.date.isoformat()}"


class PublicBooking(models.Model):
    """Public booking requests from the website."""

    SERVICE_TYPES = PUBLIC_SERVICE_TYPES

    STATUS_NEW = "new"
    STATUS_SEEN = "seen"
    STATUS_PROCESSING = "processing"
    STATUS_SCHEDULED = "scheduled"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_SEEN, "Seen"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_CLOSED, "Closed"),
    ]

    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    company = models.CharField(max_length=120, blank=True, null=True)
    service_type = models.CharField(max_length=32, choices=SERVICE_TYPES)
    pickup_location = models.CharField(max_length=255, blank=True, null=True)
    dropoff_location = models.CharField(max_length=255, blank=True, null=True)
    preferred_datetime = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )

    def __str__(self) -> str:
        return f"Booking – {self.full_name} ({self.service_type})"


class EmergencyRequest(models.Model):
    """Public emergency response requests (24/7)."""
    ISSUE_TYPES = [
        ("breakdown", "Breakdown"),
        ("electrical", "Electrical Issue"),
        ("brakes", "Brake Issue"),
        ("tire", "Tire/Flat"),
        ("no_start", "No Start"),
        ("other", "Other"),
    ]

    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    issue_type = models.CharField(max_length=32, choices=ISSUE_TYPES)
    location = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Emergency – {self.full_name} ({self.issue_type})"


class PublicContactMessage(models.Model):
    """Messages submitted from the public site or the customer portal."""

    SERVICE_TYPES = PUBLIC_SERVICE_TYPES

    STATUS_NEW = "new"
    STATUS_SEEN = "seen"
    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_SEEN, "Seen"),
    ]

    SOURCE_PUBLIC = "public"
    SOURCE_PORTAL = "portal"
    SOURCE_CHOICES = [
        (SOURCE_PUBLIC, "Public Website"),
        (SOURCE_PORTAL, "Customer Portal"),
    ]

    TYPE_GENERAL = "general"
    TYPE_SUPPORT = "support"
    TYPE_INVOICE = "invoice"
    TYPE_MAINTENANCE = "maintenance"
    TYPE_OTHER = "other"
    MESSAGE_TYPE_CHOICES = [
        (TYPE_GENERAL, "General inquiry"),
        (TYPE_SUPPORT, "Account support"),
        (TYPE_INVOICE, "Invoice question"),
        (TYPE_MAINTENANCE, "Maintenance / service"),
        (TYPE_OTHER, "Other"),
    ]

    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    company = models.CharField(max_length=120, blank=True, null=True)
    service_type = models.CharField(max_length=32, choices=SERVICE_TYPES, blank=True, null=True)
    subject = models.CharField(max_length=255, blank=True)
    message_type = models.CharField(max_length=32, choices=MESSAGE_TYPE_CHOICES, default=TYPE_GENERAL)
    reference_code = models.CharField(max_length=120, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_PUBLIC,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="submitted_contact_messages",
        blank=True,
        null=True,
    )
    customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        related_name='contact_messages',
        blank=True,
        null=True,
    )

    def __str__(self) -> str:
        topic = dict(self.MESSAGE_TYPE_CHOICES).get(self.message_type, "Contact")
        return f"{topic} – {self.full_name}"


class ActivityLog(models.Model):
    """Audit trail for business staff activity."""

    business = models.ForeignKey(
        User,
        related_name='activity_logs',
        on_delete=models.CASCADE,
        help_text="Primary business account that owns the record.",
    )
    actor = models.ForeignKey(
        User,
        related_name='performed_activities',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Staff member who performed the action.",
    )
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64, blank=True)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['business', 'created_at']),
            models.Index(fields=['object_type', 'object_id']),
        ]

    def __str__(self) -> str:
        identifier = self.object_id or str(self.pk)
        return f"{self.object_type} {identifier} – {self.action}"
