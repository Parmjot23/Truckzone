from django.utils import timezone
import datetime
from django import forms
import re
from django.db import IntegrityError
from django.db.models import Sum
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import UserCreationForm
from crispy_forms.helper import FormHelper
from django.contrib.auth.models import User
from django.forms.widgets import DateInput, TimeInput, TextInput, Select, Textarea
from django.forms import TextInput
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.forms import inlineformset_factory
from crispy_forms.layout import Submit, Layout, Fieldset, ButtonHolder, Field, Row, Div, Column
from .models import (
    Vehicle,
    WorkOrderAssignment,
    WorkOrder,
    WorkOrderRecord,
    Mechanic,
    GroupedEstimate,
    EstimateRecord,
    Driver,
    DriverSettlementStatement,
    DriverSettlementActivity,
    Customer,
    FREQUENCY_CHOICES,
    ExpenseRecord,
    IncomeRecord,
    GroupedInvoice,
    IncomeRecord2,
    InvoiceDetail,
    Profile,
    MechExpense,
    MechExpenseItem,
    SupplierCredit,
    SupplierCreditItem,
    CustomerCredit,
    CustomerCreditItem,
    SupplierCheque,
    BusinessBankAccount,
    PROVINCE_TAX_RATES,
    Note,
    Product,
    Category,
    CategoryGroup,
    CategoryAttribute,
    CategoryAttributeOption,
    ProductAttributeValue,
    Supplier,
    InventoryLocation,
    InventoryTransaction,
    ProductBrand,
    ProductModel,
    ProductVin,
    StorefrontHeroShowcase,
    StorefrontHeroShowcaseItem,
    StorefrontHeroPackage,
    StorefrontMessageBanner,
    StorefrontFlyer,
    PAYMENT_LINK_PROVIDER_CHOICES,
    FleetVehicle,
    MaintenanceRecord,
    VehicleMaintenanceTask,
    PublicBooking,
    EmergencyRequest,
    PublicContactMessage,
    BusinessBookingSettings,
    BusinessHoliday,
    BankingIntegrationSettings,
    QuickBooksSettings,
    Service,
    ServiceJobName,
    PayrollSettings,
    Employee,
    EmployeeTaxProfile,
    EmployeeRecurringDeduction,
    ShiftTemplate,
    Timesheet,
    TimeEntry,
    PayrollRun,
    PayrollTaxYear,
    PayrollProvinceTaxSetting,
    PayrollTaxBracket,
    PayrollEmployerTax,
    ConnectedBusinessGroup,
)
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.forms import BaseInlineFormSet
from .utils import (
    get_business_user,
    get_customer_user_ids,
    get_product_user_ids,
    get_product_stock_user_ids,
    calculate_next_occurrence,
)

PROVINCE_CHOICES = [
    ('AB', 'Alberta'),
    ('BC', 'British Columbia'),
    ('MB', 'Manitoba'),
    ('NB', 'New Brunswick'),
    ('NL', 'Newfoundland and Labrador'),
    ('NS', 'Nova Scotia'),
    ('ON', 'Ontario'),
    ('PE', 'Prince Edward Island'),
    ('QC', 'Quebec'),
    ('SK', 'Saskatchewan'),
    ('NT', 'Northwest Territories'),
    ('NU', 'Nunavut'),
    ('YT', 'Yukon'),
    ('CU', 'Custom'),
]


def normalize_cc_emails(value):
    if not value:
        return ''
    raw = re.split(r"[,\n;]+", str(value))
    cleaned = []
    invalid = []
    seen = set()
    for entry in raw:
        email = entry.strip()
        if not email:
            continue
        try:
            validate_email(email)
        except ValidationError:
            invalid.append(email)
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(email)
    if invalid:
        plural = "es" if len(invalid) > 1 else ""
        raise ValidationError(f"Invalid email address{plural}: {', '.join(invalid)}")
    return ", ".join(cleaned)


_ALTERNATE_SKU_SPLIT = re.compile(r"[,\n]+")


def _normalize_alternate_skus(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = _ALTERNATE_SKU_SPLIT.split(str(value))
    normalized = []
    seen = set()
    for entry in raw_items:
        sku = str(entry).strip()
        if not sku:
            continue
        key = sku.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(sku)
    return normalized

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Username or Email")


class CustomerSignupForm(forms.ModelForm):
    """Signup form used by storefront customers to create a portal account."""

    username = forms.CharField(label="Username", max_length=150)
    email = forms.EmailField(label="Email")
    cc_emails = forms.CharField(
        label="CC emails",
        required=False,
        help_text="Optional: comma-separated list of additional billing emails.",
        widget=forms.TextInput(attrs={"placeholder": "cc1@example.com, cc2@example.com"}),
    )
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput)
    gst_hst_number = forms.CharField(label="GST/HST number", max_length=20, required=False)
    collect_gst_hst = forms.BooleanField(
        label="I collect GST/HST on my invoices",
        required=False,
        initial=False,
    )

    class Meta:
        model = Customer
        fields = ["name", "phone_number", "address", "gst_hst_number", "collect_gst_hst", "cc_emails"]

    def __init__(self, *args, **kwargs):
        self.approval_required = kwargs.pop("approval_required", False)
        self.invite_customer = kwargs.pop("invite_customer", None)
        self.business_user = kwargs.pop("business_user", None)
        if self.business_user is None:
            raise ValueError("CustomerSignupForm requires a business_user instance")
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "Full name"
        self.fields["address"].widget = forms.Textarea(attrs={"rows": 3})

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another one.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if self.invite_customer:
            invite_email = (self.invite_customer.email or "").strip().lower()
            if invite_email and email != invite_email:
                raise forms.ValidationError("Please use the email address from your invite.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        if Customer.objects.filter(user=self.business_user, email__iexact=email, portal_user__isnull=False).exists():
            raise forms.ValidationError("This email is already registered as a customer.")
        return email

    def clean_cc_emails(self):
        return normalize_cc_emails(self.cleaned_data.get("cc_emails"))

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        username = self.cleaned_data["username"].strip()
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password1"]

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=self.cleaned_data.get("name", ""),
        )
        if self.approval_required:
            user.is_active = False
            user.save(update_fields=["is_active"])

        customer_defaults = {
            "name": self.cleaned_data.get("name", ""),
            "email": email,
            "cc_emails": self.cleaned_data.get("cc_emails", ""),
            "phone_number": self.cleaned_data.get("phone_number", ""),
            "address": self.cleaned_data.get("address", ""),
            "gst_hst_number": self.cleaned_data.get("gst_hst_number", ""),
            "collect_gst_hst": self.cleaned_data.get("collect_gst_hst", False),
        }

        if self.invite_customer:
            customer = self.invite_customer
            for field, value in customer_defaults.items():
                setattr(customer, field, value)
        else:
            customer, created = Customer.objects.get_or_create(
                user=self.business_user,
                email=email,
                defaults=customer_defaults,
            )

            if not created:
                for field, value in customer_defaults.items():
                    setattr(customer, field, value)

        customer.portal_user = user
        if hasattr(customer, "portal_signup_status"):
            customer.portal_signup_status = (
                Customer.PORTAL_STATUS_PENDING
                if self.approval_required
                else Customer.PORTAL_STATUS_APPROVED
            )
        if commit:
            customer.save()

        return user


class StaffSignupForm(forms.ModelForm):
    """Signup form for business staff awaiting approval."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        self.business_owner = kwargs.pop("business_owner", None)
        if self.business_owner is None:
            raise ValueError("StaffSignupForm requires a business_owner instance")
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = ""

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another one.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["username"].strip()
        user.email = self.cleaned_data["email"].strip().lower()
        user.first_name = self.cleaned_data.get("first_name", "").strip()
        user.last_name = self.cleaned_data.get("last_name", "").strip()
        user.is_staff = True
        user.is_active = False
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()
            profile = user.profile
            profile.business_owner = self.business_owner
            profile.is_business_admin = True
            profile.admin_approved = False
            profile.save()
        return user

class InvoiceCustomizationForm(forms.Form):
    invoice_header_color = forms.CharField(
        max_length=7,
        label='Header Color',
        widget=forms.TextInput(attrs={'type': 'color', 'class': 'form-control'})
    )
    invoice_font_size = forms.IntegerField(
        label='Font Size',
        min_value=8,
        max_value=72,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    show_logo = forms.BooleanField(
        label='Show Logo',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    show_address = forms.BooleanField(
        label='Show Address',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    term = forms.ChoiceField(
        label='Payment Terms',
        choices=[
            ('due_on_receipt', 'Due on Receipt'),
            ('net_2', 'Due within 2 days'),
            ('net_7', 'Due within 7 days'),
            ('net_15', 'Due within 15 days'),
            ('net_30', 'Due within 30 days'),
            ('net_45', 'Due within 45 days')
        ],
        widget=forms.Select()
    )
    payment_link_provider = forms.ChoiceField(
        label='Payment Link Provider',
        choices=PAYMENT_LINK_PROVIDER_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    show_note = forms.BooleanField(
        label='Show Note on Invoice',
        required=False,
        widget=forms.CheckboxInput()
    )
    note = forms.CharField(
        label='Invoice Note',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Enter your custom note here...'})
    )
    invoice_sequence_next = forms.IntegerField(
        label='Next Invoice Number',
        min_value=1,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text='Set the next invoice number to use. Leave blank to keep automatic numbering.',
    )
    # New field to toggle dynamic note usage
    use_dynamic_note = forms.BooleanField(
        label='Use Dynamic (AI-Generated) Note',
        required=False,
        widget=forms.CheckboxInput()
    )

    def __init__(self, *args, **kwargs):
        super(InvoiceCustomizationForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-lg-2'
        self.helper.field_class = 'col-lg-8'
        self.helper.add_input(Submit('submit', 'Save Customizations'))


class InvoiceSequenceForm(forms.Form):
    invoice_sequence_next = forms.IntegerField(
        label='Next Invoice Number',
        min_value=1,
        required=False,
        widget=forms.NumberInput(
            attrs={'class': 'form-control', 'placeholder': 'Auto'}
        ),
        help_text='Leave blank to keep automatic numbering.',
    )


class ConnectedBusinessGroupForm(forms.ModelForm):
    class Meta:
        model = ConnectedBusinessGroup
        fields = ["name", "share_customers", "share_products", "share_product_stock"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }


class QRCodeStyleForm(forms.Form):
    qr_code_font_scale = forms.IntegerField(
        label='Font Size Scale (%)',
        min_value=20,
        max_value=160,
        widget=forms.NumberInput(
            attrs={
                'type': 'range',
                'class': 'form-range w-100',
                'step': 5,
                'min': 20,
                'max': 160,
            }
        ),
    )
    show_product_name = forms.BooleanField(
        label='Product name',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    show_product_description = forms.BooleanField(
        label='Product description',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    show_product_sku = forms.BooleanField(
        label='Product SKU',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

# Custom widget for phone number input
class PhoneNumberWidget(TextInput):
    def __init__(self, attrs=None):
        default_attrs = {
            'placeholder': 'Enter phone number',
            'class': 'form-control'
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

def format_phone_number(value):
    # Remove unwanted characters and ensure only digits are left
    value = ''.join(filter(str.isdigit, value))

    # Handle case where number starts with "1" and has more than 10 digits
    if value.startswith("1") and len(value) > 10:
        value = value[1:]  # Remove the leading "1" to format the number correctly

    # Ensure the number has at least 10 digits after processing
    if len(value) >= 10:
        formatted_number = f"+1({value[:3]}){value[3:6]}-{value[6:10]}"
        if len(value) > 10:
            formatted_number += f"{value[10:]}"  # Append any extra digits
        return formatted_number

    # If the number is less than 10 digits, return the original value unformatted
    return value

def validate_phone_number(value):
    return format_phone_number(value)

# Custom field for phone number with automatic formatting
class PhoneNumberField(forms.CharField):
    def to_python(self, value):
        if not value:
            return ''
        return validate_phone_number(value)

class ProfileForm(forms.ModelForm):
    # -- Phone Fields --
    company_phone_1 = PhoneNumberField(
        required=False,
        label="Phone Number 1",
        widget=PhoneNumberWidget(attrs={'placeholder': 'Enter primary phone number'})
    )
    company_phone_2 = PhoneNumberField(
        required=False,
        label="Phone Number 2 (optional)",
        widget=PhoneNumberWidget(attrs={'placeholder': 'Enter secondary phone number'})
    )

    company_fax = PhoneNumberField(
        required=False,
        label="Fax Number",
        widget=PhoneNumberWidget(attrs={'placeholder': 'Enter fax number'})
    )

    # -- Interact Email Fields --
    use_company_email_as_interact_email = forms.BooleanField(
        required=False,
        label="Use company email as interact email",
        initial=False
    )
    interact_email = forms.EmailField(
        required=False,
        label="Interact Email",
        widget=forms.EmailInput(attrs={
            'placeholder': 'This email is used for asking users for payments.'
        })
    )

    class Meta:
        model = Profile
        fields = [
            'company_name',
            'storefront_display_name',
            'storefront_is_visible',
            'company_email',
            'interact_email',
            'use_company_email_as_interact_email',
            'company_fax',
            'gst_hst_number',
            'company_logo',
            'occupation',
            'street_address',
            'city',
            'province',
            'postal_code',
            'wsib_number',
            'qst_number',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'storefront_display_name' in self.fields:
            self.fields['storefront_display_name'].label = "Store location name"
            self.fields['storefront_display_name'].help_text = (
                "Shown to customers when selecting a store location."
            )
            self.fields['storefront_display_name'].widget.attrs.setdefault(
                'placeholder',
                'e.g. Montreal - East',
            )
        if 'storefront_is_visible' in self.fields:
            self.fields['storefront_is_visible'].label = "Show in storefront selector"
            self.fields['storefront_is_visible'].help_text = (
                "Turn off to hide this location from the My Store switcher."
            )
            self.fields['storefront_is_visible'].widget.attrs.setdefault(
                'class',
                'form-check-input',
            )

        # Determine the province from instance or form data
        province = self.instance.province if self.instance and self.instance.province else self.data.get('province')
        qst_visible = province == 'QC'
        qst_wrapper_class = 'qst-field' if qst_visible else 'qst-field d-none'

        # Setup Crispy Forms
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Update your Profile',
                'company_name',
                'storefront_display_name',
                'storefront_is_visible',
                'company_email',
                Div(
                    Div('use_company_email_as_interact_email', css_class='col-md-3'),
                    Div('interact_email', css_class='col-md-9'),
                    css_class='form-row'
                ),
                Field('company_phone_1', css_class='form-group'),
                Field('company_phone_2', css_class='form-group'),
                Field('company_fax', css_class='form-group'),
                'gst_hst_number',
                'company_logo',
                'occupation',
                'street_address',
                'city',
                'province',
                'postal_code',
                Div('qst_number', css_class=qst_wrapper_class, css_id='qst-field'),
                # Conditional fields will be added below
            ),
            ButtonHolder(
                Submit('submit', 'Save Profile', css_class='btn btn-primary')
            )
        )

                # WSIB number field removed for truck mechanics focus

        if 'qst_number' in self.fields:
            self.fields['qst_number'].required = False
            self.fields['qst_number'].label = "QST Number"
            self.fields['qst_number'].help_text = "Enter your QST number (e.g., 1234567890TQ0001)."

        # Pre-populate phone fields if profile already has phone numbers
        if self.instance and self.instance.company_phone:
            phone_numbers = self.instance.company_phone.split(', ')
            if len(phone_numbers) > 0:
                self.fields['company_phone_1'].initial = phone_numbers[0]
            if len(phone_numbers) > 1:
                self.fields['company_phone_2'].initial = phone_numbers[1]

        if self.instance and self.instance.company_fax:
            self.fields['company_fax'].initial = self.instance.company_fax

        # Set initial interact email fields
        if self.instance:
            if self.instance.interact_email:
                self.fields['interact_email'].initial = self.instance.interact_email
                self.fields['use_company_email_as_interact_email'].initial = (
                    self.instance.interact_email == self.instance.company_email
                )
            else:
                self.fields['interact_email'].initial = ''
                self.fields['use_company_email_as_interact_email'].initial = False

    def clean(self):
        cleaned_data = super().clean()

        # Validate phone numbers
        phone_number_1 = cleaned_data.get('company_phone_1')
        phone_number_2 = cleaned_data.get('company_phone_2')
        fax_number = cleaned_data.get('company_fax')
        if phone_number_1:
            cleaned_data['company_phone_1'] = validate_phone_number(phone_number_1)
        if phone_number_2:
            cleaned_data['company_phone_2'] = validate_phone_number(phone_number_2)
        if fax_number:
            cleaned_data['company_fax'] = validate_phone_number(fax_number)

        # Handle Interact Email logic
        use_company_email = cleaned_data.get('use_company_email_as_interact_email')
        interact_email = cleaned_data.get('interact_email')

        if use_company_email:
            if not cleaned_data.get('company_email'):
                self.add_error('company_email', "Company email must be set if you want to use it as interact email.")
            else:
                cleaned_data['interact_email'] = cleaned_data.get('company_email')
        else:
            if not interact_email:
                self.add_error('interact_email', "Please provide an interact email or select to use the company email.")

        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)

        # Manually set GST/HST Number to ensure it's saved
        profile.gst_hst_number = self.cleaned_data.get('gst_hst_number', '')

        # If qst_number is present in cleaned_data, save that too
        if 'qst_number' in self.cleaned_data:
            profile.qst_number = self.cleaned_data['qst_number']

        # Handle phone numbers
        phone_numbers = []
        phone_1 = self.cleaned_data.get('company_phone_1')
        phone_2 = self.cleaned_data.get('company_phone_2')
        if phone_1:
            phone_numbers.append(format_phone_number(phone_1))
        if phone_2:
            phone_numbers.append(format_phone_number(phone_2))
        profile.company_phone = ', '.join(phone_numbers)

        fax_number = self.cleaned_data.get('company_fax')
        profile.company_fax = format_phone_number(fax_number) if fax_number else ''

        # Handle Interact Email
        profile.interact_email = self.cleaned_data.get('interact_email')

        if commit:
            profile.save()
        return profile


class DisplayPreferencesForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['ui_scale_percentage', 'ui_scale_public_percentage']
        labels = {
            'ui_scale_percentage': 'Portal & dashboard pages',
            'ui_scale_public_percentage': 'Public pages',
        }
        help_texts = {
            'ui_scale_percentage': 'Choose how compact the back-office and customer portal pages should appear.',
            'ui_scale_public_percentage': 'Adjust how compact the public marketing pages should appear.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('ui_scale_percentage', 'ui_scale_public_percentage'):
            self.fields[field_name].widget.attrs.update({'class': 'form-select'})


class StorefrontHeroShowcaseForm(forms.ModelForm):
    class Meta:
        model = StorefrontHeroShowcase
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-select')


class StorefrontHeroShowcaseItemForm(forms.ModelForm):
    class Meta:
        model = StorefrontHeroShowcaseItem
        fields = ['product', 'discount_percent']
        widgets = {
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 100, 'step': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'product' in self.fields:
            self.fields['product'].widget.attrs.setdefault('class', 'form-select')
            self.fields['product'].widget.attrs['data-hero-product'] = 'true'
        if 'discount_percent' in self.fields:
            self.fields['discount_percent'].widget.attrs.setdefault('class', 'form-control')
            self.fields['discount_percent'].widget.attrs['data-hero-discount'] = 'true'


class StorefrontHeroPackageForm(forms.ModelForm):
    class Meta:
        model = StorefrontHeroPackage
        fields = [
            'title',
            'subtitle',
            'primary_product',
            'secondary_product',
            'free_product',
            'discount_percent',
            'is_active',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'subtitle': forms.TextInput(attrs={'class': 'form-control'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 100, 'step': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('primary_product', 'secondary_product', 'free_product'):
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.setdefault('class', 'form-select')
        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.setdefault('class', 'form-check-input')
        if 'title' in self.fields:
            self.fields['title'].widget.attrs['data-hero-package-title'] = 'true'
        if 'subtitle' in self.fields:
            self.fields['subtitle'].widget.attrs['data-hero-package-subtitle'] = 'true'
        if 'primary_product' in self.fields:
            self.fields['primary_product'].widget.attrs['data-hero-package-primary'] = 'true'
        if 'secondary_product' in self.fields:
            self.fields['secondary_product'].widget.attrs['data-hero-package-secondary'] = 'true'
        if 'free_product' in self.fields:
            self.fields['free_product'].widget.attrs['data-hero-package-free'] = 'true'
        if 'discount_percent' in self.fields:
            self.fields['discount_percent'].widget.attrs['data-hero-package-discount'] = 'true'


class StorefrontPriceVisibilityForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'storefront_show_prices_hero',
            'storefront_show_prices_featured',
            'storefront_show_prices_catalog',
            'storefront_show_empty_categories',
        ]
        labels = {
            'storefront_show_prices_hero': 'Show prices in promo highlights for guests',
            'storefront_show_prices_featured': 'Show prices in featured sections for guests',
            'storefront_show_prices_catalog': 'Show prices across all product pages for guests',
            'storefront_show_empty_categories': 'Show categories even when no products are published',
        }
        help_texts = {
            'storefront_show_prices_hero': 'When off, promo pricing is hidden unless the customer signs in.',
            'storefront_show_prices_featured': 'When off, featured pricing is hidden unless the customer signs in.',
            'storefront_show_prices_catalog': 'When off, product listings and details hide prices unless signed in.',
            'storefront_show_empty_categories': 'Keeps category groups and category pages visible when inventory is empty.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-check-input')


class StorefrontMessageBannerForm(forms.ModelForm):
    class Meta:
        model = StorefrontMessageBanner
        fields = ['is_active', 'message', 'link_text', 'link_url', 'theme']
        widgets = {
            'message': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter banner message'}),
            'link_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional link label'}),
            'link_url': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'https:// or /path'}),
            'theme': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'theme': 'Banner style',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.setdefault('class', 'form-check-input')


class StorefrontFlyerForm(forms.ModelForm):
    class Meta:
        model = StorefrontFlyer
        fields = ['is_active', 'title', 'subtitle']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Package Deals & Discounts'}),
            'subtitle': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Highlight hero offers and bundle savings.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.setdefault('class', 'form-check-input')


class FlyerEmailForm(forms.Form):
    AUDIENCE_CHOICES = [
        ("test", "Send test to me"),
        ("all_customers", "All customers with email"),
    ]

    template_key = forms.ChoiceField(
        label="Template",
        choices=(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    audience = forms.ChoiceField(
        label="Audience",
        choices=AUDIENCE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Email subject"}),
    )
    preheader = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Short preview text"}),
    )
    headline = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Main headline"}),
    )
    subheadline = forms.CharField(
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Secondary headline"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Main message"}),
    )
    highlights = forms.CharField(
        required=False,
        help_text="One highlight per line.",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Highlight 1\nHighlight 2\nHighlight 3"}),
    )
    cta_text = forms.CharField(
        required=False,
        max_length=60,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Button text"}),
    )
    cta_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
    )
    footer_note = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Footer note (optional)"}),
    )

    def __init__(self, *args, template_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        if template_choices:
            self.fields["template_key"].choices = template_choices

    def clean(self):
        cleaned = super().clean()
        cta_text = (cleaned.get("cta_text") or "").strip()
        cta_url = (cleaned.get("cta_url") or "").strip()
        if cta_text and not cta_url:
            self.add_error("cta_url", "Provide a CTA URL when CTA text is set.")
        if cta_url and not cta_text:
            self.add_error("cta_text", "Provide CTA text when a CTA URL is set.")
        return cleaned


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ['title', 'content']  # Fields to be displayed in the form
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Note Title'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Write your note here...'}),
        }


class PaymentForm(forms.Form):
    stripe_token = forms.CharField(widget=forms.HiddenInput())
    billing_name = forms.CharField(max_length=255, required=True, label='Full Name')
    billing_address = forms.CharField(max_length=255, required=True, label='Street Address')
    billing_city = forms.CharField(max_length=100, required=True, label='City')
    billing_province = forms.ChoiceField(choices=PROVINCE_CHOICES, required=True, label='Province')
    billing_postal_code = forms.CharField(max_length=7, required=True, label='Postal Code')

    def __init__(self, *args, **kwargs):
        super(PaymentForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-lg-2'
        self.helper.field_class = 'col-lg-8'
        self.helper.add_input(Submit('submit', 'Submit Payment', css_class='btn btn-primary'))

class SignUpForm(UserCreationForm):
    email = forms.EmailField(max_length=254, required=True)
    first_name = forms.CharField(max_length=30, required=True)
    occupation = forms.ChoiceField(
        choices=[
            ('truck_mechanic', 'Truck Mechanic'),
            ('towing', 'Towing'),
            ('parts_store', 'Parts Store'),
        ],
        required=True,
    )
    province = forms.ChoiceField(choices=PROVINCE_CHOICES, required=True)

    class Meta:
        model = User
        fields = ('first_name', 'email', 'password1', 'password2', 'occupation', 'province')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data.get('first_name').lower()
        existing_user_count = User.objects.filter(username__startswith=first_name).count()
        proposed_username = f"{first_name}{existing_user_count + 1}" if existing_user_count > 0 else first_name

        while User.objects.filter(username=proposed_username).exists():
            existing_user_count += 1
            proposed_username = f"{first_name}{existing_user_count}"

        cleaned_data['username'] = proposed_username
        return cleaned_data

    def save(self, commit=True):
        user = super(SignUpForm, self).save(commit=False)
        user.username = self.cleaned_data['username']
        user.first_name = self.cleaned_data['first_name']
        user.email = self.cleaned_data['email']

        if commit:
            user.save()
            user.profile.occupation = self.cleaned_data.get('occupation')
            user.profile.province = self.cleaned_data.get('province')
            user.profile.save()

        return user


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = ExpenseRecord
        fields = ['date', 'fuel', 'plates', 'wsib', 'repairs', 'parking', 'wash', 'def_fluid', 'insurance']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(ExpenseForm, self).__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super(ExpenseForm, self).save(commit=False)
        if not instance.user_id:
            instance.user = self.user
        if commit:
            instance.save()
        return instance

# Define categories with additional options
MECHANIC_CATEGORIES = [
    ('Parts', 'Parts'),  # Default option
    ('Labour', 'Labour'),
    ('Fuel', 'Fuel'),
    ('Rent', 'Rent'),
    ('Lease', 'Lease'),
    ('Installment', 'Installment'),
    ('Insurance', 'Insurance'),
    ('Supplies', 'Supplies'),
    ('Miscellaneous', 'Miscellaneous'),
    ('Tools', 'Tools'),
    # Add more categories as needed
]

class MechExpenseForm(forms.ModelForm):
    custom_tax_rate = forms.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=Decimal('0'),
        required=False,
        label='Custom Tax Rate (%)',
        help_text='Enter the tax rate as a percentage (e.g., 13 for 13%).',
    )
    record_in_inventory = forms.BooleanField(
        required=False,
        initial=True,
        label='Track these items in inventory',
        help_text='Turn off for non-inventory expenses like rent, lease, or installments.',
    )
    vendor = forms.CharField(
        label='Supplier',
        widget=forms.TextInput(
            attrs={
                'list': 'vendor_list',
                'placeholder': 'Start typing a supplier name',
            }
        ),
    )
    receipt_no = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Enter receipt number'}),
        help_text='Leave blank to auto-generate',
    )
    categorie = forms.ChoiceField(choices=MECHANIC_CATEGORIES, initial='Parts')
    unit_number = forms.CharField(
        required=False,
        label="Unit Number",
        widget=forms.TextInput(attrs={'placeholder': 'Unit # (Optional)'}),
    )
    odometer_reading = forms.IntegerField(required=False, label="Odometer Reading")  # For "Fuel" category
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    tax_included = forms.BooleanField(required=False, label="Tax Included")
    province = forms.ChoiceField(choices=PROVINCE_CHOICES, required=False, label="Tax rate")

    # Recurring fields
    is_recurring = forms.BooleanField(required=False, label="Is Recurring")
    frequency = forms.ChoiceField(choices=FREQUENCY_CHOICES, required=False)

    class Meta:
        model = MechExpense
        fields = [
            'date', 'vendor', 'receipt_no', 'categorie', 'unit_number',
            'odometer_reading', 'start_date', 'end_date',
            'tax_included', 'paid', 'province', 'custom_tax_rate',
            'record_in_inventory',
            'is_recurring', 'frequency'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(MechExpenseForm, self).__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        for date_field in ['date', 'start_date', 'end_date']:
            field = self.fields.get(date_field)
            if field:
                existing_attrs = field.widget.attrs.copy()
                existing_attrs['max'] = today
                field.widget.attrs = existing_attrs
        # Populate categories from defaults and user's custom categories
        choices = MECHANIC_CATEGORIES.copy()
        if self.user:
            user_categories = Category.objects.filter(user=self.user).values_list('name', flat=True)
            for cat in user_categories:
                option = (cat, cat)
                if option not in choices:
                    choices.append(option)
        self.fields['categorie'].choices = choices

        self.fields['custom_tax_rate'].widget.attrs.update({'placeholder': 'e.g., 13 for 13%'})

        # Default province to user's profile province
        if self.user and hasattr(self.user, 'profile'):
            self.fields['province'].initial = self.user.profile.province
        else:
            self.fields['province'].initial = 'ON'  # Default to Ontario if no profile

        if self.instance and self.instance.custom_tax_rate is not None:
            self.fields['custom_tax_rate'].initial = (
                Decimal(self.instance.custom_tax_rate) * Decimal('100')
            ).quantize(Decimal('0.0001'))

    def clean_date(self):
        value = self.cleaned_data.get('date')
        if value and value > timezone.localdate():
            raise forms.ValidationError('Date cannot be in the future.')
        return value

    def clean_custom_tax_rate(self):
        value = self.cleaned_data.get('custom_tax_rate')
        if value in (None, ''):
            return None

        if value > Decimal('1'):
            value = (value / Decimal('100')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        else:
            value = Decimal(value).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return value

    def clean(self):
        cleaned_data = super().clean()
        categorie = cleaned_data.get('categorie')
        odometer_reading = cleaned_data.get('odometer_reading')
        unit_number = cleaned_data.get('unit_number')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        is_recurring = cleaned_data.get('is_recurring')
        frequency = cleaned_data.get('frequency')
        today = timezone.localdate()

        # Validate odometer_reading for Fuel category
        if categorie == 'Fuel' and not odometer_reading:
            self.add_error('odometer_reading', 'Odometer reading is required for Fuel category.')
        if unit_number is not None:
            cleaned_data['unit_number'] = unit_number.strip() or None
        if categorie != 'Fuel':
            cleaned_data['unit_number'] = None

        # Validate start_date and end_date for specific categories
        if categorie in ['Rent', 'Insurance']:
            if not start_date or not end_date:
                self.add_error('start_date', 'Start and end dates are required for this category.')
            elif end_date < start_date:
                self.add_error('end_date', 'End date cannot be before start date.')

        for field_name, value in [('start_date', start_date), ('end_date', end_date)]:
            if value and value > today:
                self.add_error(field_name, 'Date cannot be in the future.')

        # Validate recurring fields
        if is_recurring and not frequency:
            self.add_error('frequency', 'Frequency is required for recurring expenses.')

        province = cleaned_data.get('province')
        custom_tax_rate = cleaned_data.get('custom_tax_rate')
        if province == 'CU':
            if custom_tax_rate is None:
                self.add_error('custom_tax_rate', 'Please enter a custom tax rate.')
        else:
            cleaned_data['custom_tax_rate'] = None

        return cleaned_data

    def save(self, commit=True):
        instance = super(MechExpenseForm, self).save(commit=False)
        if not instance.user_id:
            instance.user = self.user
        cleaned_custom_tax_rate = self.cleaned_data.get('custom_tax_rate')
        province = self.cleaned_data.get('province')
        if province == 'CU':
            instance.custom_tax_rate = cleaned_custom_tax_rate
        else:
            instance.custom_tax_rate = None
        is_recurring = self.cleaned_data.get('is_recurring')
        frequency = self.cleaned_data.get('frequency')
        if is_recurring and frequency:
            base_date = instance.date or timezone.localdate()
            instance.next_occurrence = calculate_next_occurrence(base_date, frequency)
        else:
            instance.next_occurrence = None
        if commit:
            instance.save()
        return instance

class MechExpenseItemForm(forms.ModelForm):
    inventory_product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label='Inventory Product',
    )
    create_inventory_product = forms.BooleanField(
        required=False,
        initial=True,
        label='Create or update this product in inventory',
    )

    class Meta:
        model = MechExpenseItem
        fields = ['part_no', 'description', 'qty', 'price']
        widgets = {
            'part_no': forms.TextInput(attrs={'placeholder': 'Enter part number'}),
            'description': forms.Textarea(attrs={'placeholder': 'Enter description', 'rows': 2}),
            'qty': forms.NumberInput(attrs={'min': '0'}),
            'price': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        self.categorie = kwargs.pop('categorie', 'Parts')
        self.user = kwargs.pop('user', None)
        super(MechExpenseItemForm, self).__init__(*args, **kwargs)
        # Ensure new/empty inline forms don't look "changed" when left blank so
        # they can be ignored by the formset (empty_permitted relies on has_changed()).
        if not self.instance.pk:
            self.initial['qty'] = ''
            self.initial['price'] = ''
        if self.user:
            product_user_ids = get_product_user_ids(self.user)
            self.fields['inventory_product'].queryset = Product.objects.filter(
                user__in=product_user_ids
            ).order_by('name')
        else:
            self.fields['inventory_product'].queryset = Product.objects.none()
        self.fields['inventory_product'].widget.attrs.update({'class': 'form-control inventory-product-select'})
        self.fields['create_inventory_product'].widget.attrs.update({'class': 'create-inventory-checkbox'})
        self._required_categories = ['Parts', 'Supplies', 'Miscellaneous', 'Tools']
        self.fields['part_no'].required = False  # enforce manually in clean()

    def has_meaningful_data(self, cleaned_data):
        if not cleaned_data:
            return False
        return any(
            cleaned_data.get(field) not in (None, '', [], {}, 0, 0.0)
            for field in ('inventory_product', 'qty', 'price', 'description', 'part_no')
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('part_no'):
            # Prefer incoming selection, else use instance data, else selected product.
            if self.instance and getattr(self.instance, 'part_no', None):
                cleaned['part_no'] = self.instance.part_no
            elif self.instance and getattr(self.instance, 'inventory_product', None):
                cleaned['part_no'] = self.instance.inventory_product.sku or ''
            elif cleaned.get('inventory_product'):
                cleaned['part_no'] = cleaned['inventory_product'].sku or ''
        if self.categorie in self._required_categories and self.has_meaningful_data(cleaned):
            if not cleaned.get('part_no'):
                self.add_error('part_no', 'This field is required.')
        return cleaned

class BaseMechExpenseItemFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.categorie = kwargs.pop('categorie', 'Parts')
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['categorie'] = self.categorie
        kwargs['user'] = self.user
        return kwargs

    def clean(self):
        """
        Treat completely blank extra rows as deleted so they don't raise
        required-field errors when the user leaves them empty.
        """
        super().clean()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            # If all primary fields are blank/empty, silently drop the row.
            fields = ['part_no', 'description', 'qty', 'price', 'inventory_product']
            if any(form.cleaned_data.get(f) not in (None, '', 0, 0.0) for f in fields):
                continue
            form.cleaned_data['DELETE'] = True
            form._errors = form.error_class()

MechExpenseItemFormSet = inlineformset_factory(
    MechExpense,
    MechExpenseItem,
    form=MechExpenseItemForm,
    formset=BaseMechExpenseItemFormSet,
    extra=0,  # Start with no extra blank rows; users add rows as needed
    can_delete=True
)

class SupplierCreditForm(forms.ModelForm):
    custom_tax_rate = forms.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=Decimal('0'),
        required=False,
        label='Custom Tax Rate (%)',
        help_text='Enter the tax rate as a percentage (e.g., 13 for 13%).',
    )
    record_in_inventory = forms.BooleanField(
        required=False,
        initial=True,
        label='Track these items in inventory',
        help_text='Turn off for non-inventory credits like adjustments or rebates.',
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=True,
        label='Supplier',
    )
    credit_no = forms.CharField(
        required=False,
        label='Credit Number',
        widget=forms.TextInput(attrs={'placeholder': 'Enter credit number'}),
        help_text='Leave blank to auto-generate',
    )
    memo = forms.CharField(
        required=False,
        label='Memo',
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Add a memo for this credit'}),
    )
    tax_included = forms.BooleanField(required=False, label="Tax Included")
    province = forms.ChoiceField(choices=PROVINCE_CHOICES, required=False, label="Tax rate")

    class Meta:
        model = SupplierCredit
        fields = [
            'date',
            'supplier',
            'credit_no',
            'memo',
            'tax_included',
            'province',
            'custom_tax_rate',
            'record_in_inventory',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        if 'date' in self.fields:
            date_attrs = self.fields['date'].widget.attrs.copy()
            date_attrs['max'] = today
            self.fields['date'].widget.attrs = date_attrs
        if self.user:
            self.fields['supplier'].queryset = Supplier.objects.filter(user=self.user).order_by('name')
        else:
            self.fields['supplier'].queryset = Supplier.objects.none()
        self.fields['custom_tax_rate'].widget.attrs.update({'placeholder': 'e.g., 13 for 13%'})

        def _format_percent(value):
            percent_value = Decimal(str(value)) * Decimal('100')
            formatted = format(percent_value.normalize(), 'f')
            if '.' in formatted:
                formatted = formatted.rstrip('0').rstrip('.')
            return formatted

        province_choices = []
        for code, label in PROVINCE_CHOICES:
            if code == 'CU':
                choice_label = f"{label} (custom rate)"
            else:
                rate_value = PROVINCE_TAX_RATES.get(code, 0)
                choice_label = f"{label} ({_format_percent(rate_value)}%)"
            province_choices.append((code, choice_label))
        self.fields['province'].choices = province_choices

        if self.user and hasattr(self.user, 'profile'):
            self.fields['province'].initial = self.user.profile.province
        else:
            self.fields['province'].initial = 'ON'

        if self.instance and self.instance.custom_tax_rate is not None:
            self.fields['custom_tax_rate'].initial = (
                Decimal(self.instance.custom_tax_rate) * Decimal('100')
            ).quantize(Decimal('0.0001'))

    def clean_date(self):
        value = self.cleaned_data.get('date')
        if value and value > timezone.localdate():
            raise forms.ValidationError('Date cannot be in the future.')
        return value

    def clean_custom_tax_rate(self):
        value = self.cleaned_data.get('custom_tax_rate')
        if value in (None, ''):
            return None
        if value > Decimal('1'):
            value = (value / Decimal('100')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        else:
            value = Decimal(value).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return value

    def clean(self):
        cleaned_data = super().clean()
        province = cleaned_data.get('province')
        custom_tax_rate = cleaned_data.get('custom_tax_rate')
        if province == 'CU':
            if custom_tax_rate is None:
                self.add_error('custom_tax_rate', 'Please enter a custom tax rate.')
        else:
            cleaned_data['custom_tax_rate'] = None
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.user_id:
            instance.user = self.user
        cleaned_custom_tax_rate = self.cleaned_data.get('custom_tax_rate')
        province = self.cleaned_data.get('province')
        if province == 'CU':
            instance.custom_tax_rate = cleaned_custom_tax_rate
        else:
            instance.custom_tax_rate = None
        if commit:
            instance.save()
        return instance


class SupplierCreditItemForm(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label='Inventory Product',
    )
    create_inventory_product = forms.BooleanField(
        required=False,
        initial=True,
        label='Create or update this product in inventory',
    )

    class Meta:
        model = SupplierCreditItem
        fields = [
            'product',
            'part_no',
            'description',
            'qty',
            'price',
            'source_expense',
            'source_expense_item',
        ]
        widgets = {
            'part_no': forms.TextInput(attrs={'placeholder': 'Enter part number'}),
            'description': forms.Textarea(attrs={'placeholder': 'Enter description', 'rows': 2}),
            'qty': forms.NumberInput(attrs={'min': '0', 'step': '1'}),
            'price': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'source_expense': forms.HiddenInput(),
            'source_expense_item': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            product_user_ids = get_product_user_ids(self.user)
            self.fields['product'].queryset = Product.objects.filter(
                user__in=product_user_ids
            ).order_by('name')
        else:
            self.fields['product'].queryset = Product.objects.none()
        self.fields['product'].widget.attrs.update({'class': 'form-control credit-product-select'})
        self.fields['create_inventory_product'].widget.attrs.update({'class': 'create-inventory-checkbox'})

    def has_meaningful_data(self, cleaned_data):
        if not cleaned_data:
            return False
        return any(
            cleaned_data.get(field) not in (None, '', [], {}, 0, 0.0)
            for field in ('product', 'qty', 'price', 'description', 'part_no')
        )


class BaseSupplierCreditItemFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['user'] = self.user
        return kwargs

    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            fields = ['product', 'part_no', 'description', 'qty', 'price']
            if any(form.cleaned_data.get(f) not in (None, '', 0, 0.0) for f in fields):
                continue
            form.cleaned_data['DELETE'] = True
            form._errors = form.error_class()

        profile = getattr(self.user, 'profile', None)
        enforce_invoice_links = bool(profile and getattr(profile, 'occupation', None) == 'parts_store')
        if enforce_invoice_links:
            for form in self.forms:
                if not hasattr(form, 'cleaned_data'):
                    continue
                if form.cleaned_data.get('DELETE'):
                    continue
                if form.cleaned_data.get('source_invoice_item'):
                    continue
                if getattr(form, 'instance', None) and getattr(form.instance, 'pk', None):
                    continue
                if form.has_meaningful_data(form.cleaned_data):
                    form.add_error(
                        'source_invoice_item',
                        'Select an invoice item to return.',
                    )

        # Prevent returning more than was invoiced for linked invoice items.
        items_to_check = []
        source_ids = set()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            source_item = form.cleaned_data.get('source_invoice_item')
            if not source_item:
                continue
            line_type = getattr(source_item, 'line_type', '') or ''
            if line_type in ('', 'custom') and getattr(source_item, 'product_id', None):
                line_type = 'product'
            if line_type not in ('product', 'core_charge'):
                form.add_error(
                    'source_invoice_item',
                    'Only product or core returns are allowed from invoices.',
                )
                continue
            qty_raw = form.cleaned_data.get('qty')
            try:
                qty_dec = Decimal(str(qty_raw or 0))
            except (TypeError, ValueError, InvalidOperation):
                qty_dec = Decimal('0.00')
            if qty_dec <= Decimal('0.00'):
                continue
            items_to_check.append((form, source_item, qty_dec))
            source_ids.add(source_item.id)

        if not source_ids:
            return

        existing_qs = CustomerCreditItem.objects.filter(source_invoice_item_id__in=source_ids)
        if getattr(self.instance, 'pk', None):
            existing_qs = existing_qs.exclude(customer_credit=self.instance)

        existing_totals = {
            row['source_invoice_item_id']: Decimal(str(row['total_qty'] or 0))
            for row in existing_qs.values('source_invoice_item_id').annotate(total_qty=Sum('qty'))
        }

        pending_totals = {}
        for form, source_item, qty_dec in items_to_check:
            item_id = source_item.id
            pending_totals[item_id] = pending_totals.get(item_id, Decimal('0.00')) + qty_dec
            max_qty = Decimal(str(source_item.qty or 0))
            remaining = max_qty - existing_totals.get(item_id, Decimal('0.00'))
            if pending_totals[item_id] > remaining:
                available = remaining if remaining > Decimal('0.00') else Decimal('0.00')
                available_display = available.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                form.add_error(
                    'qty',
                    f"Only {available_display} available to return for this invoice line.",
                )


SupplierCreditItemFormSet = inlineformset_factory(
    SupplierCredit,
    SupplierCreditItem,
    form=SupplierCreditItemForm,
    formset=BaseSupplierCreditItemFormSet,
    extra=0,
    can_delete=True,
)


class CustomerCreditForm(forms.ModelForm):
    custom_tax_rate = forms.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=Decimal('0'),
        required=False,
        label='Custom Tax Rate (%)',
        help_text='Enter the tax rate as a percentage (e.g., 13 for 13%).',
    )
    record_in_inventory = forms.BooleanField(
        required=False,
        initial=True,
        label='Track these items in inventory',
        help_text='Turn off for non-inventory credits like adjustments or rebates.',
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=True,
        label='Customer',
    )
    credit_no = forms.CharField(
        required=False,
        label='Credit Number',
        widget=forms.TextInput(attrs={'placeholder': 'Enter credit number'}),
        help_text='Leave blank to auto-generate',
    )
    memo = forms.CharField(
        required=False,
        label='Memo',
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Add a memo for this credit'}),
    )
    tax_included = forms.BooleanField(required=False, label="Tax Included")
    province = forms.ChoiceField(choices=PROVINCE_CHOICES, required=False, label="Tax rate")

    class Meta:
        model = CustomerCredit
        fields = [
            'date',
            'customer',
            'credit_no',
            'memo',
            'tax_included',
            'province',
            'custom_tax_rate',
            'record_in_inventory',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        if 'date' in self.fields:
            date_attrs = self.fields['date'].widget.attrs.copy()
            date_attrs['max'] = today
            self.fields['date'].widget.attrs = date_attrs
        if self.user:
            business_user_ids = get_customer_user_ids(self.user)
            self.fields['customer'].queryset = Customer.objects.filter(
                user__in=business_user_ids
            ).order_by('name')
        else:
            self.fields['customer'].queryset = Customer.objects.none()
        self.fields['custom_tax_rate'].widget.attrs.update({'placeholder': 'e.g., 13 for 13%'})

        def _format_percent(value):
            percent_value = Decimal(str(value)) * Decimal('100')
            formatted = format(percent_value.normalize(), 'f')
            if '.' in formatted:
                formatted = formatted.rstrip('0').rstrip('.')
            return formatted

        province_choices = []
        for code, label in PROVINCE_CHOICES:
            if code == 'CU':
                choice_label = f"{label} (custom rate)"
            else:
                rate_value = PROVINCE_TAX_RATES.get(code, 0)
                choice_label = f"{label} ({_format_percent(rate_value)}%)"
            province_choices.append((code, choice_label))
        self.fields['province'].choices = province_choices

        if self.user and hasattr(self.user, 'profile'):
            self.fields['province'].initial = self.user.profile.province
        else:
            self.fields['province'].initial = 'ON'

        if self.instance and self.instance.custom_tax_rate is not None:
            self.fields['custom_tax_rate'].initial = (
                Decimal(self.instance.custom_tax_rate) * Decimal('100')
            ).quantize(Decimal('0.0001'))

    def clean_date(self):
        value = self.cleaned_data.get('date')
        if value and value > timezone.localdate():
            raise forms.ValidationError('Date cannot be in the future.')
        return value

    def clean_custom_tax_rate(self):
        value = self.cleaned_data.get('custom_tax_rate')
        if value in (None, ''):
            return None
        if value > Decimal('1'):
            value = (value / Decimal('100')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        else:
            value = Decimal(value).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return value

    def clean(self):
        cleaned_data = super().clean()
        province = cleaned_data.get('province')
        custom_tax_rate = cleaned_data.get('custom_tax_rate')
        if province == 'CU':
            if custom_tax_rate is None:
                self.add_error('custom_tax_rate', 'Please enter a custom tax rate.')
        else:
            cleaned_data['custom_tax_rate'] = None
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.user_id:
            instance.user = self.user
        cleaned_custom_tax_rate = self.cleaned_data.get('custom_tax_rate')
        province = self.cleaned_data.get('province')
        if province == 'CU':
            instance.custom_tax_rate = cleaned_custom_tax_rate
        else:
            instance.custom_tax_rate = None
        if commit:
            instance.save()
        return instance


class CustomerCreditItemForm(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label='Inventory Product',
    )
    create_inventory_product = forms.BooleanField(
        required=False,
        initial=True,
        label='Create or update this product in inventory',
    )

    class Meta:
        model = CustomerCreditItem
        fields = [
            'product',
            'part_no',
            'description',
            'qty',
            'price',
            'source_invoice',
            'source_invoice_item',
        ]
        widgets = {
            'part_no': forms.TextInput(attrs={'placeholder': 'Enter part number'}),
            'description': forms.Textarea(attrs={'placeholder': 'Enter description', 'rows': 2}),
            'qty': forms.NumberInput(attrs={'min': '0', 'step': '1'}),
            'price': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'source_invoice': forms.HiddenInput(),
            'source_invoice_item': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            product_user_ids = get_product_user_ids(self.user)
            self.fields['product'].queryset = Product.objects.filter(
                user__in=product_user_ids
            ).order_by('name')
        else:
            self.fields['product'].queryset = Product.objects.none()
        self.fields['product'].widget.attrs.update({'class': 'form-control credit-product-select'})
        self.fields['create_inventory_product'].widget.attrs.update({'class': 'create-inventory-checkbox'})

    def has_meaningful_data(self, cleaned_data):
        if not cleaned_data:
            return False
        return any(
            cleaned_data.get(field) not in (None, '', [], {}, 0, 0.0)
            for field in ('product', 'qty', 'price', 'description', 'part_no')
        )


class BaseCustomerCreditItemFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['user'] = self.user
        return kwargs

    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            fields = ['product', 'part_no', 'description', 'qty', 'price']
            if any(form.cleaned_data.get(f) not in (None, '', 0, 0.0) for f in fields):
                continue
            form.cleaned_data['DELETE'] = True
            form._errors = form.error_class()


CustomerCreditItemFormSet = inlineformset_factory(
    CustomerCredit,
    CustomerCreditItem,
    form=CustomerCreditItemForm,
    formset=BaseCustomerCreditItemFormSet,
    extra=0,
    can_delete=True,
)


class SupplierChequeForm(forms.ModelForm):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=True,
        label='Supplier',
    )
    bank_account = forms.ChoiceField(
        required=False,
        choices=[],
        label='Bank Account',
    )

    class Meta:
        model = SupplierCheque
        fields = ['date', 'supplier', 'cheque_number', 'bank_account', 'memo']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'cheque_number': forms.TextInput(attrs={'placeholder': 'Cheque #'}),
            'bank_account': forms.Select(attrs={'class': 'form-select'}),
            'memo': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Memo (optional)'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields['supplier'].queryset = Supplier.objects.filter(user=self.user).order_by('name')
        else:
            self.fields['supplier'].queryset = Supplier.objects.none()
        bank_choices = [('', 'Select bank account')]
        if self.user:
            accounts = BusinessBankAccount.objects.filter(user=self.user, is_active=True).order_by('name', 'id')
            bank_choices.extend(
                (account.display_label, account.display_label)
                for account in accounts
            )
        self.fields['bank_account'].choices = bank_choices
        today = timezone.localdate().isoformat()
        if 'date' in self.fields:
            date_attrs = self.fields['date'].widget.attrs.copy()
            date_attrs['max'] = today
            self.fields['date'].widget.attrs = date_attrs


class IncomeForm(forms.ModelForm):
    JOB_CHOICES = [
        ('hourly', 'Hourly'),
        ('load', 'Load'),
    ]
    job = forms.ChoiceField(choices=JOB_CHOICES)

    class Meta:
        model = IncomeRecord
        fields = ['date', 'ticket', 'jobsite', 'truck', 'job', 'qty', 'rate']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(IncomeForm, self).__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super(IncomeForm, self).save(commit=False)
        if not instance.user_id:
            instance.user = self.user
        if commit:
            instance.save()
        return instance

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = InvoiceDetail
        fields = ['bill_to']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(InvoiceForm, self).__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super(InvoiceForm, self).save(commit=False)
        if not instance.user_id:
            instance.user = self.user
        if commit:
            instance.save()
        return instance

class DateInput(forms.DateInput):
    input_type = 'date'

class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = [
            'name',
            'pay_rate',
            'extra_hours',
            'gst_hst_number',
            'pay_gst_hst',
            'license_number',
            'phone',
            'email',
            'address',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'name',
            Row(
                Div('pay_rate', css_class='col-md-6'),
                Div('extra_hours', css_class='col-md-6'),
            ),
            'gst_hst_number',
            'pay_gst_hst',
            'license_number',
            Row(
                Div('phone', css_class='col-md-6'),
                Div('email', css_class='col-md-6'),
            ),
            'address',
            ButtonHolder(
                Submit('submit', 'Save Driver', css_class='btn btn-primary')
            )
        )


class GroupedInvoiceForm(forms.ModelForm):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    invoice_number = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Leave blank to keep automatic numbering.',
    )

    class Meta:
        model = GroupedInvoice
        fields = [
            'date', 'customer', 'po_number', 'vin_no', 'mileage',
            'unit_no', 'make_model', 'license_plate', 'date_from', 'date_to',
            'is_subscription', 'subscription_frequency', 'tax_exempt', 'tax_exempt_reason', 'notes'
        ]
        widgets = {
            'date': DateInput(attrs={'class': 'form-control'}),
            'po_number': forms.TextInput(attrs={'class': 'form-control'}),
            'date_from': DateInput(attrs={'class': 'form-control'}),
            'date_to': DateInput(attrs={'class': 'form-control'}),
            'vin_no': forms.TextInput(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_no': forms.TextInput(attrs={'class': 'form-control'}),
            'make_model': forms.TextInput(attrs={'class': 'form-control'}),
            'license_plate': forms.TextInput(attrs={'class': 'form-control'}),
            'is_subscription': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'subscription_frequency': forms.Select(attrs={'class': 'form-control'}),
            'tax_exempt': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_tax_exempt'}),
            'tax_exempt_reason': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_tax_exempt_reason', 'list': 'tax-exemption-reasons'}),
            'notes': Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(GroupedInvoiceForm, self).__init__(*args, **kwargs)

        if self.user:
            business_user_ids = get_customer_user_ids(self.user)
            self.fields['customer'].queryset = Customer.objects.filter(user__in=business_user_ids)

        non_required_fields = ['vin_no', 'mileage', 'unit_no', 'make_model', 'license_plate', 'notes']
        for field in non_required_fields:
            if field in self.fields:
                self.fields[field].required = False

        # Set the PO number field as non-required by default
        if 'po_number' in self.fields:
            self.fields['po_number'].required = False

        self.fields['vin_no'].label = 'VIN Number'
        self.fields['mileage'].label = 'Mileage'
        self.fields['unit_no'].label = 'Unit Number'
        self.fields['make_model'].label = 'Make and Model'
        if 'license_plate' in self.fields:
            self.fields['license_plate'].label = 'License Plate'
        # Remove date range fields
        for field in ['date_from', 'date_to']:
            self.fields.pop(field, None)

        if 'tax_exempt_reason' in self.fields:
            self.fields['tax_exempt_reason'].required = False

        profile_note = ''
        profile = getattr(self.user, 'profile', None) if self.user else None
        if profile and profile.note:
            profile_note = (profile.note or '').strip()
        self._profile_note_default = profile_note

        if 'notes' in self.fields:
            if not self.instance.pk or not (self.instance.notes or '').strip():
                if profile_note and not self.is_bound:
                    self.fields['notes'].initial = profile_note

        if 'invoice_number' in self.fields:
            self.fields['invoice_number'].label = 'Invoice Number'
            if not self.is_bound and not self.instance.pk:
                resolved_user = self.user or getattr(self.instance, 'user', None)
                if resolved_user and not self.initial.get('invoice_number'):
                    self.fields['invoice_number'].initial = GroupedInvoice.generate_invoice_number(
                        resolved_user,
                        commit=False,
                    )

        if 'date' in self.fields and not self.is_bound and not self.instance.pk:
            if not self.initial.get('date'):
                self.fields['date'].initial = timezone.localdate()

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Invoice Details',
                'invoice_number',
                'date',
                'customer',
                'po_number',  # Added PO number in the layout so it appears on the form
                'vin_no',
                'mileage',
                'unit_no',
                'make_model',
                'license_plate',
                'date_from',
                'date_to',
                'is_subscription',
                'subscription_frequency',
                'tax_exempt',
                'tax_exempt_reason',
            ),
            Fieldset(
                'Notes',
                'notes',
            ),
            ButtonHolder(
                Submit('submit', 'Save changes', css_class='btn btn-success')
            )
        )

    def clean_invoice_number(self):
        raw_value = self.cleaned_data.get('invoice_number', '')
        value = (raw_value or '').strip()
        if not value:
            return self.instance.invoice_number or None

        invoice_user = self.user or getattr(self.instance, 'user', None)
        if invoice_user:
            exists = GroupedInvoice.objects.filter(
                user=invoice_user,
                invoice_number__iexact=value,
            ).exclude(pk=self.instance.pk).exists()
            if exists:
                raise forms.ValidationError('That invoice number is already in use.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        is_subscription = cleaned_data.get('is_subscription')
        freq = cleaned_data.get('subscription_frequency')
        if is_subscription and not freq:
            self.add_error('subscription_frequency', 'Please select a frequency for subscription invoices.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        invoice_number = self.cleaned_data.get('invoice_number')
        if invoice_number is not None:
            instance.invoice_number = invoice_number
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CustomerForm(forms.ModelForm):
    """
    - Uses charge_rate (what you charge the customer) for everyone.
    - Uses a TypedChoiceField for collect_gst_hst, mapping back in clean().
    - Enforces unique customer names per user.
    """

    cc_emails = forms.CharField(
        label="CC emails",
        required=False,
        help_text="Optional: comma-separated list of additional billing emails.",
        widget=forms.TextInput(attrs={"placeholder": "cc1@example.com, cc2@example.com"}),
    )
    collect_gst_hst_choice = forms.TypedChoiceField(
        label="Do you collect GST/HST from this customer?",
        choices=[('True', 'Yes'), ('False', 'No')],
        coerce=lambda x: x == 'True',
        widget=forms.RadioSelect,
        required=False
    )

    register_portal = forms.BooleanField(
        required=False,
        label="Enable customer portal access",
        help_text="Give this customer a login so they can view invoices, work orders, and products.",
    )
    portal_username = forms.CharField(
        required=False,
        label="Portal username",
    )
    portal_password = forms.CharField(
        required=False,
        label="Temporary password",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = Customer
        fields = [
            'name',
            'email',
            'cc_emails',
            'address',
            'phone_number',
            'gst_hst_number',
            'charge_rate',           # renamed field
        ]

    def __init__(self, *args, **kwargs):
        # pull out the user for conditional logic
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.customer_owner = get_business_user(self.user) or self.user
        self.instance_owner = (
            self.instance.user
            if getattr(self.instance, 'user_id', None)
            else self.customer_owner
        )

        # Crispy Forms setup
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        layout_fields = [
            'name',
            'email',
            'cc_emails',
            'address',
            'phone_number',
            'gst_hst_number',
            'charge_rate',           # always visible
        ]
        if 'collect_gst_hst_choice' in self.fields:
            layout_fields.append('collect_gst_hst_choice')
        layout_fields.extend([
            'register_portal',
            'portal_username',
            'portal_password',
        ])
        self.helper.layout = Layout(
            *layout_fields,
            Submit('submit', 'Save Customer', css_class='btn btn-primary btn-lg mt-3')
        )

        # GST/HST logic simplified for truck mechanics
        profile = getattr(self.user, 'profile', None)
        allowed_provinces = ['MB', 'BC', 'QC', 'SK']
        if profile and profile.province not in allowed_provinces:
            self.fields['collect_gst_hst_choice'].required = True
        else:
            # remove the radio and default to False
            self.fields.pop('collect_gst_hst_choice', None)
            self.instance.collect_gst_hst = False

        portal_user = getattr(self.instance, 'portal_user', None)
        if portal_user:
            self.fields['register_portal'].initial = portal_user.is_active
            self.fields['portal_username'].initial = portal_user.username
        else:
            self.fields['register_portal'].initial = False

        for field_name in ['portal_username', 'portal_password']:
            field = self.fields.get(field_name)
            if field:
                field.widget.attrs.setdefault('data-customer-portal-field', '1')

    def clean(self):
        cleaned_data = super().clean()
        # map the radio choice back to the model boolean
        if 'collect_gst_hst_choice' in self.fields:
            self.instance.collect_gst_hst = cleaned_data.get('collect_gst_hst_choice', False)
        register = cleaned_data.get('register_portal')
        username = cleaned_data.get('portal_username') or ''
        password = cleaned_data.get('portal_password') or ''
        if register:
            if not username:
                self.add_error('portal_username', 'Please provide a username for the customer portal.')
            if not self.instance.portal_user and not password:
                self.add_error('portal_password', 'Please provide a temporary password for the customer.')
        return cleaned_data

    def clean_cc_emails(self):
        return normalize_cc_emails(self.cleaned_data.get("cc_emails"))

    def clean_name(self):
        """
        Enforce unique customer name for this user (case-insensitive).
        """
        name = self.cleaned_data.get('name')
        owner = self.instance_owner
        if not owner:
            raise ValidationError("User information is missing.")

        qs = Customer.objects.filter(user=owner, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A customer with this name already exists.")
        return name

    def clean_portal_username(self):
        username = (self.cleaned_data.get('portal_username') or '').strip()
        if not self.cleaned_data.get('register_portal'):
            return username
        if not username:
            raise ValidationError('Please provide a username for the customer portal.')
        existing = User.objects.filter(username__iexact=username)
        if self.instance.portal_user_id:
            existing = existing.exclude(pk=self.instance.portal_user_id)
        if existing.exists():
            raise ValidationError('This username is already taken. Choose a different one.')
        return username

    def save(self, commit=True):
        customer = super().save(commit=False)
        if not getattr(customer, 'user_id', None):
            if not getattr(self, 'user', None):
                raise ValueError('CustomerForm.save requires a user to be provided when creating a customer.')
            customer.user = self.customer_owner or self.user

        register = self.cleaned_data.get('register_portal')
        username = (self.cleaned_data.get('portal_username') or '').strip()
        password = self.cleaned_data.get('portal_password') or ''
        portal_user = customer.portal_user
        if register and hasattr(customer, "portal_signup_status"):
            customer.portal_signup_status = Customer.PORTAL_STATUS_APPROVED

        if commit:
            customer.save()
            self.save_m2m()

        if register and username:
            if portal_user:
                portal_user.username = username
                if customer.email:
                    portal_user.email = customer.email
                portal_user.is_active = True
                if password:
                    portal_user.set_password(password)
                portal_user.save()
            else:
                portal_user = User.objects.create_user(
                    username=username,
                    email=customer.email or ''
                )
                if password:
                    portal_user.set_password(password)
                else:
                    portal_user.set_unusable_password()
                portal_user.is_active = True
                portal_user.save()
                customer.portal_user = portal_user
                if commit:
                    customer.save(update_fields=['portal_user'])
        elif portal_user:
            # Disable access without removing the relationship entirely.
            if portal_user.is_active:
                portal_user.is_active = False
                portal_user.save()

        return customer


class CustomerPortalProfileForm(forms.ModelForm):
    """Form used by customer portal users to manage their own profile details."""

    class Meta:
        model = Customer
        fields = ['name', 'email', 'cc_emails', 'phone_number', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'cc_emails': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'cc1@example.com, cc2@example.com'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Mailing address'}),
        }
        labels = {
            'name': 'Name',
            'email': 'Email',
            'cc_emails': 'CC emails',
            'phone_number': 'Phone number',
            'address': 'Address',
        }

    def clean_cc_emails(self):
        return normalize_cc_emails(self.cleaned_data.get("cc_emails"))


class CustomerStatementForm(forms.Form):
    PERIOD_CHOICES = [
        ('week', 'Weekly'),
        ('month', 'Monthly'),
        ('quarter', 'Quarterly'),
        ('semiannual', 'Semiannual'),
        ('annual', 'Annual'),
    ]
    EXPORT_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        initial='month',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Statement interval',
        help_text='Choose how the invoices should be grouped.',
    )
    reference_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Reference date',
        help_text='Statements align to calendar boundaries that include this date.',
    )
    export_format = forms.ChoiceField(
        choices=EXPORT_CHOICES,
        required=False,
        widget=forms.HiddenInput(),
    )


class ReceiptUploadForm(forms.Form):
    file = forms.FileField(label="Upload Receipt")

class IncomeRecord2Form(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        widget=forms.HiddenInput()
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = IncomeRecord2
        fields = ['job', 'qty', 'rate', 'date', 'ticket', 'jobsite', 'truck', 'product', 'driver', 'line_order']
        widgets = {
            'job': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe labor/job performed',
            }),
            'date': DateInput(),
            'jobsite': forms.TextInput(attrs={'list': 'jobsite_list'}),
            'truck': forms.TextInput(attrs={'list': 'truck_list'}),
            'line_order': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(IncomeRecord2Form, self).__init__(*args, **kwargs)
        if user:
            business_user = get_business_user(user)
            product_user_ids = get_product_user_ids(user)
            self.fields['product'].queryset = Product.objects.filter(user__in=product_user_ids)
            # Always include the driver field
            drivers = Driver.objects.filter(user=business_user)
            if self.instance and self.instance.pk and self.instance.driver:
                # Ensure the instance's driver is included even if not normally in the queryset
                drivers = (drivers | Driver.objects.filter(pk=self.instance.driver.pk)).distinct()
            self.fields['driver'].queryset = drivers

        self.fields['job'].label = 'Description'
        self.fields['qty'].label = 'Quantity'

        self.fields['rate'].label = 'Price'
        for field in ['date', 'ticket', 'jobsite', 'truck']:
            self.fields[field].required = False

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Div(Field('job'), css_class='col-12 col-md-6'),
                Div(Field('qty'), css_class='col-6 col-md-3'),
                Div(Field('rate'), css_class='col-6 col-md-3'),
            ),
            Field('product'),
            Field('driver')
        )

IncomeRecord2FormSet = inlineformset_factory(
    GroupedInvoice,
    IncomeRecord2,
    form=IncomeRecord2Form,
    extra=0,
    can_delete=True
)




class CategoryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user

        if self.user:
            if 'group' in self.fields:
                self.fields['group'].queryset = CategoryGroup.objects.filter(user=self.user).order_by('sort_order', 'name')
            if 'parent' in self.fields:
                parent_qs = Category.objects.filter(user=self.user).order_by('sort_order', 'name')
                if self.instance and self.instance.pk:
                    parent_qs = parent_qs.exclude(pk=self.instance.pk)
                self.fields['parent'].queryset = parent_qs

    class Meta:
        model = Category
        exclude = ['user']
        labels = {
            'name': 'Category Name',
            'description': 'Category Description',
            'group': 'Category Group',
            'parent': 'Parent Category',
            'image': 'Category Image',
            'sort_order': 'Sort Order',
            'is_active': 'Active',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter category name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Brief description of the category'}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        if self.user and normalized:
            qs = Category.objects.filter(user=self.user, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a category with this name.')
        return normalized


class CategoryGroupForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user

    class Meta:
        model = CategoryGroup
        exclude = ['user']
        labels = {
            'name': 'Group Name',
            'description': 'Group Description',
            'image': 'Group Image',
            'sort_order': 'Sort Order',
            'is_active': 'Active',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter group name'}),
            'description': forms.Textarea(attrs={'placeholder': 'Brief description of the group'}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        if self.user and normalized:
            qs = CategoryGroup.objects.filter(user=self.user, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a category group with this name.')
        return normalized


class CategoryAttributeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user
        if self.user:
            self.fields['category'].queryset = Category.objects.filter(user=self.user).order_by('sort_order', 'name')

    class Meta:
        model = CategoryAttribute
        exclude = ['user']
        labels = {
            'name': 'Attribute Name',
            'description': 'Attribute Description',
            'value_unit': 'Value Unit',
            'attribute_type': 'Attribute Type',
            'category': 'Category',
            'is_filterable': 'Filterable',
            'is_comparable': 'Comparable',
            'sort_order': 'Sort Order',
            'is_active': 'Active',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Brake Type'}),
            'description': forms.Textarea(attrs={'placeholder': 'Optional help text'}),
            'value_unit': forms.TextInput(attrs={'placeholder': 'e.g. inch, psi'}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        category = self.cleaned_data.get('category')
        if self.user and normalized and category:
            qs = CategoryAttribute.objects.filter(category=category, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('This category already has an attribute with this name.')
        return normalized


class ProductBrandForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user

    class Meta:
        model = ProductBrand
        exclude = ['user']
        labels = {
            'name': 'Brand Name',
            'description': 'Brand Description',
            'logo': 'Brand Logo',
            'sort_order': 'Sort Order',
            'is_active': 'Active',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Freightliner'}),
            'description': forms.Textarea(attrs={'placeholder': 'Optional brand description'}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        if self.user and normalized:
            qs = ProductBrand.objects.filter(user=self.user, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a brand with this name.')
        return normalized


class ProductModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user
        if self.user and 'brand' in self.fields:
            self.fields['brand'].queryset = ProductBrand.objects.filter(user=self.user).order_by('sort_order', 'name')

    class Meta:
        model = ProductModel
        exclude = ['user']
        labels = {
            'name': 'Model Name',
            'brand': 'Brand',
            'description': 'Model Description',
            'year_start': 'Year Start',
            'year_end': 'Year End',
            'sort_order': 'Sort Order',
            'is_active': 'Active',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Cascadia'}),
            'description': forms.Textarea(attrs={'placeholder': 'Optional model description'}),
            'year_start': forms.NumberInput(attrs={'min': 0}),
            'year_end': forms.NumberInput(attrs={'min': 0}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        if self.user and normalized:
            qs = ProductModel.objects.filter(user=self.user, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a model with this name.')
        return normalized


class ProductVinForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user

    class Meta:
        model = ProductVin
        exclude = ['user']
        labels = {
            'vin': 'VIN',
            'description': 'VIN Description',
            'sort_order': 'Sort Order',
            'is_active': 'Active',
        }
        widgets = {
            'vin': forms.TextInput(attrs={'placeholder': '17-character VIN'}),
            'description': forms.Textarea(attrs={'placeholder': 'Optional VIN notes'}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }

    def clean_vin(self):
        vin = self.cleaned_data.get('vin', '')
        normalized = vin.strip().upper()
        if self.user and normalized:
            qs = ProductVin.objects.filter(user=self.user, vin__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have this VIN saved.')
        return normalized

class SupplierForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user

    class Meta:
        model = Supplier
        exclude = ['user', 'portal_user']
        labels = {
            'name': 'Supplier Name',
            'contact_person': 'Contact Person',
            'email': 'Email Address',
            'phone_number': 'Phone Number',
            'address': 'Address',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Enter supplier name'}),
            'contact_person': forms.TextInput(attrs={'placeholder': 'Enter contact person name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'example@supplier.com'}),
            'phone_number': forms.TextInput(attrs={'placeholder': 'Enter contact phone number'}),
            'address': forms.Textarea(attrs={'placeholder': 'Enter full address'}),
        }


    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        if self.user and normalized:
            qs = Supplier.objects.filter(user=self.user, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a supplier with this name.')
        return normalized


class SupplierPortalForm(forms.Form):
    register_portal = forms.BooleanField(
        required=False,
        label='Enable supplier login',
        help_text='Allow this supplier to sign in to their dedicated portal.',
    )
    portal_username = forms.CharField(
        required=False,
        label='Portal username',
    )
    portal_password = forms.CharField(
        required=False,
        label='Temporary password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Provide a password for new accounts or leave blank to keep the current one.',
    )

    def __init__(self, *args, supplier=None, **kwargs):
        if supplier is None:
            raise ValueError('SupplierPortalForm requires a supplier instance.')
        self.supplier = supplier
        super().__init__(*args, **kwargs)

        portal_user = getattr(self.supplier, 'portal_user', None)
        if portal_user:
            self.fields['register_portal'].initial = portal_user.is_active
            self.fields['portal_username'].initial = portal_user.username
            self.fields['portal_password'].help_text = 'Leave blank to keep the current password.'
        else:
            self.fields['register_portal'].initial = True

    def clean(self):
        cleaned_data = super().clean()
        username = (cleaned_data.get('portal_username') or '').strip()
        cleaned_data['portal_username'] = username

        register = cleaned_data.get('register_portal')
        password = cleaned_data.get('portal_password') or ''

        if register:
            if not username:
                self.add_error('portal_username', 'Please provide a username for the supplier portal.')
            if not getattr(self.supplier, 'portal_user', None) and not password:
                self.add_error('portal_password', 'Please provide a temporary password for the supplier.')

        return cleaned_data

    def clean_portal_username(self):
        username = (self.cleaned_data.get('portal_username') or '').strip()
        if not self.cleaned_data.get('register_portal'):
            return username
        if not username:
            raise forms.ValidationError('Please provide a username for the supplier portal.')

        existing = User.objects.filter(username__iexact=username)
        portal_user = getattr(self.supplier, 'portal_user', None)
        if portal_user_id := getattr(portal_user, 'id', None):
            existing = existing.exclude(pk=portal_user_id)
        if existing.exists():
            raise forms.ValidationError('This username is already taken. Choose a different one.')
        return username

    def save(self):
        supplier = self.supplier
        register = self.cleaned_data.get('register_portal')
        username = (self.cleaned_data.get('portal_username') or '').strip()
        password = self.cleaned_data.get('portal_password') or ''
        portal_user = getattr(supplier, 'portal_user', None)

        if register and username:
            if portal_user:
                portal_user.username = username
                if supplier.email:
                    portal_user.email = supplier.email
                portal_user.is_active = True
                if password:
                    portal_user.set_password(password)
                portal_user.save()
            else:
                portal_user = User.objects.create_user(
                    username=username,
                    email=supplier.email or ''
                )
                if password:
                    portal_user.set_password(password)
                else:
                    portal_user.set_unusable_password()
                portal_user.is_active = True
                portal_user.save()
                supplier.portal_user = portal_user
                supplier.save(update_fields=['portal_user'])
        elif portal_user and portal_user.is_active:
            portal_user.is_active = False
            portal_user.save(update_fields=['is_active'])

        return supplier


class AccountantPortalForm(forms.Form):
    register_portal = forms.BooleanField(
        required=False,
        label="Enable accountant portal access",
        help_text="Allow your accountant to sign in to a read-only portal.",
    )
    portal_username = forms.CharField(
        required=False,
        label="Portal username",
    )
    portal_password = forms.CharField(
        required=False,
        label="Temporary password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Provide a password for new accounts or leave blank to keep the current one.",
    )

    def __init__(self, *args, profile=None, **kwargs):
        if profile is None:
            raise ValueError("AccountantPortalForm requires a profile instance.")
        self.profile = profile
        super().__init__(*args, **kwargs)

        portal_user = getattr(self.profile, "accountant_portal_user", None)
        if portal_user:
            self.fields["register_portal"].initial = portal_user.is_active
            self.fields["portal_username"].initial = portal_user.username
            self.fields["portal_password"].help_text = "Leave blank to keep the current password."
        else:
            self.fields["register_portal"].initial = True

    def clean(self):
        cleaned_data = super().clean()
        username = (cleaned_data.get("portal_username") or "").strip()
        cleaned_data["portal_username"] = username

        register = cleaned_data.get("register_portal")
        password = cleaned_data.get("portal_password") or ""

        if register:
            if not username:
                self.add_error("portal_username", "Please provide a username for the accountant portal.")
            if not getattr(self.profile, "accountant_portal_user", None) and not password:
                self.add_error("portal_password", "Please provide a temporary password for the accountant.")

        return cleaned_data

    def clean_portal_username(self):
        username = (self.cleaned_data.get("portal_username") or "").strip()
        if not self.cleaned_data.get("register_portal"):
            return username
        if not username:
            raise forms.ValidationError("Please provide a username for the accountant portal.")

        existing = User.objects.filter(username__iexact=username)
        portal_user = getattr(self.profile, "accountant_portal_user", None)
        if portal_user_id := getattr(portal_user, "id", None):
            existing = existing.exclude(pk=portal_user_id)
        if existing.exists():
            raise forms.ValidationError("This username is already taken. Choose a different one.")
        return username

    def save(self):
        profile = self.profile
        register = self.cleaned_data.get("register_portal")
        username = (self.cleaned_data.get("portal_username") or "").strip()
        password = self.cleaned_data.get("portal_password") or ""
        portal_user = getattr(profile, "accountant_portal_user", None)

        if register and username:
            if portal_user:
                portal_user.username = username
                if profile.accountant_email:
                    portal_user.email = profile.accountant_email
                portal_user.is_active = True
                if password:
                    portal_user.set_password(password)
                portal_user.save()
            else:
                portal_user = User.objects.create_user(
                    username=username,
                    email=profile.accountant_email or "",
                )
                if password:
                    portal_user.set_password(password)
                else:
                    portal_user.set_unusable_password()
                portal_user.is_active = True
                portal_user.save()
                profile.accountant_portal_user = portal_user
                profile.save(update_fields=["accountant_portal_user"])
        elif portal_user and portal_user.is_active:
            portal_user.is_active = False
            portal_user.save(update_fields=["is_active"])

        return profile


class ServiceForm(forms.ModelForm):
    job_name = forms.CharField(
        label='Job name',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'e.g. Inspection, Maintenance, Repair',
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['job_name'].widget.attrs.setdefault('list', 'job-name-options')
        self.fields['name'].widget = forms.Textarea(
            attrs={
                'rows': 2,
                'placeholder': 'Describe the job as it should appear on invoices and work orders',
            }
        )
        self.fields['description'].widget.attrs.update(
            {
                'rows': 2,
                'placeholder': 'Add more context or internal notes about this job (optional)',
            }
        )
        fixed_hours_field = self.fields.get('fixed_hours')
        if fixed_hours_field:
            fixed_hours_field.widget = forms.NumberInput(
                attrs={
                    'min': '0',
                    'step': '0.25',
                    'placeholder': 'e.g. 2.5',
                }
            )
            fixed_hours_field.required = False
        fixed_rate_field = self.fields.get('fixed_rate')
        if fixed_rate_field:
            fixed_rate_field.widget = forms.NumberInput(
                attrs={
                    'min': '0',
                    'step': '0.01',
                    'placeholder': 'e.g. 125.00',
                }
            )
            fixed_rate_field.required = False

        for field_name in ['due_after_kilometers', 'due_after_months']:
            field = self.fields.get(field_name)
            if field:
                field.widget = forms.NumberInput(
                    attrs={
                        'min': '0',
                        'step': '1',
                        'placeholder': 'e.g. 5000' if field_name == 'due_after_kilometers' else 'e.g. 6',
                    }
                )
                field.required = False

        portal_field = self.fields.get('show_on_customer_portal')
        if portal_field:
            portal_field.label = 'Show on customer vehicle list'
            portal_field.widget = forms.CheckboxInput(
                attrs={
                    'class': 'form-check-input',
                }
            )

        if self.instance.pk and self.instance.job_name_id:
            self.fields['job_name'].initial = self.instance.job_name.name

    class Meta:
        model = Service
        fields = [
            'name',
            'description',
            'fixed_hours',
            'fixed_rate',
            'due_after_kilometers',
            'due_after_months',
            'show_on_customer_portal',
        ]
        labels = {
            'name': 'Job description',
            'description': 'More about this job',
            'fixed_hours': 'Fixed hours (optional)',
            'fixed_rate': 'Fixed rate (optional)',
            'due_after_kilometers': 'Due after (km)',
            'due_after_months': 'Due after (months)',
            'show_on_customer_portal': 'Show on customer vehicle list',
        }

    def clean_job_name(self):
        job_name_raw = (self.cleaned_data.get('job_name') or '').strip()
        if not job_name_raw:
            raise forms.ValidationError('Please provide a job name.')

        normalized_job_name = re.sub(r'\s+', ' ', job_name_raw).strip()
        if not normalized_job_name:
            raise forms.ValidationError('Please provide a job name.')

        if not self.user:
            raise forms.ValidationError('We could not determine which account to use for this job name.')

        job_group = ServiceJobName.objects.filter(
            user=self.user,
            name__iexact=normalized_job_name,
        ).first()

        if not job_group:
            job_group = ServiceJobName(user=self.user, name=normalized_job_name)
            try:
                job_group.save()
            except IntegrityError:
                job_group = ServiceJobName.objects.filter(
                    user=self.user,
                    name__iexact=normalized_job_name,
                ).first()
                if not job_group:
                    raise forms.ValidationError('We could not save that job name. Please try again.')

        # Preserve a display-only version for other validation steps or templates if needed.
        self.cleaned_data['job_name_display'] = job_group.name
        return job_group

    def clean_fixed_hours(self):
        fixed_hours = self.cleaned_data.get('fixed_hours')
        if fixed_hours is not None and fixed_hours < 0:
            raise forms.ValidationError('Fixed hours cannot be negative.')
        return fixed_hours

    def clean_fixed_rate(self):
        fixed_rate = self.cleaned_data.get('fixed_rate')
        if fixed_rate is not None and fixed_rate < 0:
            raise forms.ValidationError('Fixed rate cannot be negative.')
        return fixed_rate

    def clean_due_after_kilometers(self):
        value = self.cleaned_data.get('due_after_kilometers')
        if value is not None and value < 0:
            raise forms.ValidationError('Kilometer interval cannot be negative.')
        return value

    def clean_due_after_months(self):
        value = self.cleaned_data.get('due_after_months')
        if value is not None and value < 0:
            raise forms.ValidationError('Month interval cannot be negative.')
        return value

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = Service._normalize_text(name)
        if not normalized:
            raise forms.ValidationError('Please provide a job description.')
        return normalized

    def clean(self):
        cleaned_data = super().clean()
        job_name_value = cleaned_data.get('job_name')
        name_value = cleaned_data.get('name')
        show_on_portal = cleaned_data.get('show_on_customer_portal')
        if show_on_portal and self.user:
            portal_qs = Service.objects.filter(user=self.user, show_on_customer_portal=True)
            if self.instance.pk:
                portal_qs = portal_qs.exclude(pk=self.instance.pk)
            if portal_qs.count() >= 4:
                self.add_error(
                    'show_on_customer_portal',
                    'Limit reached: choose up to 4 services for the customer vehicle list.',
                )
        if self.user and job_name_value and name_value:
            if isinstance(job_name_value, ServiceJobName):
                job_group = job_name_value
            else:
                normalized_job_name = re.sub(r'\s+', ' ', str(job_name_value)).strip()
                job_group = ServiceJobName.objects.filter(
                    user=self.user,
                    name__iexact=normalized_job_name,
                ).first()

            qs = Service.objects.filter(user=self.user)
            if job_group:
                qs = qs.filter(job_name=job_group)
            qs = qs.filter(name__iexact=name_value)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if job_group and qs.exists():
                self.add_error('name', 'You already saved this job description under that job name.')
        return cleaned_data

    def save(self, commit=True):
        job_group = self.cleaned_data['job_name']
        if not isinstance(job_group, ServiceJobName):
            normalized_job_name = re.sub(r'\s+', ' ', str(job_group)).strip()
            job_group = ServiceJobName.objects.filter(
                user=self.user,
                name__iexact=normalized_job_name,
            ).first()
            if not job_group:
                job_group = ServiceJobName(user=self.user, name=normalized_job_name)
                job_group.save()

        instance = super().save(commit=False)
        instance.user = self.user
        instance.job_name = job_group
        if commit:
            instance.save()
        return instance


class InventoryLocationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user

    class Meta:
        model = InventoryLocation
        exclude = ["user"]
        labels = {
            "name": "Location Name",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Warehouse A"}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        if self.user and normalized:
            qs = InventoryLocation.objects.filter(user=self.user, name__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a location with this name.')
        return normalized


class ProductForm(forms.ModelForm):
    alternate_skus = forms.CharField(
        required=False,
        label="Alternate / Interchange SKUs",
        help_text="Separate multiple SKUs with commas or new lines.",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "e.g. ABC-123, DEF-456",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        category_id_override = kwargs.pop('category_id', None)
        self.user = user
        self.category_id_override = category_id_override
        self.attribute_field_names = []
        self.attribute_map = {}
        self.attribute_fields = []
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user
        if self.user:
            # Only show suppliers and categories that belong to the logged-in user
            self.fields['supplier'].queryset = Supplier.objects.filter(user=self.user)
            self.fields['category'].queryset = Category.objects.filter(user=self.user)
            if 'brand' in self.fields:
                self.fields['brand'].queryset = ProductBrand.objects.filter(user=self.user, is_active=True).order_by('sort_order', 'name')
            if 'vehicle_model' in self.fields:
                self.fields['vehicle_model'].queryset = ProductModel.objects.filter(user=self.user, is_active=True).order_by('sort_order', 'name')
            if 'vin_number' in self.fields:
                self.fields['vin_number'].queryset = ProductVin.objects.filter(user=self.user, is_active=True).order_by('sort_order', 'vin')
            locations = InventoryLocation.objects.filter(user=self.user)
            choices = [('', '---------')] + [(loc.name, loc.name) for loc in locations]
            self.fields['location'] = forms.ChoiceField(
                choices=choices,
                required=False,
                label='Location',
            )
            if self.instance and self.instance.location:
                self.fields['location'].initial = self.instance.location
        if 'category' in self.fields:
            self.fields['category'].widget.attrs.setdefault('data-attribute-source', 'true')
        if 'is_published_to_store' in self.fields:
            self.fields['is_published_to_store'].widget.attrs.update({'class': 'form-check-input'})
        if 'is_featured' in self.fields:
            self.fields['is_featured'].widget.attrs.update({'class': 'form-check-input'})
        if 'sku' in self.fields:
            self.fields['sku'].required = False
        if 'margin' in self.fields:
            self.fields['margin'].required = False
        if 'sale_price' in self.fields:
            self.fields['sale_price'].required = False
        if 'promotion_price' in self.fields:
            self.fields['promotion_price'].required = False
        if 'core_price' in self.fields:
            self.fields['core_price'].required = False
        if 'environmental_fee' in self.fields:
            self.fields['environmental_fee'].required = False
        if 'alternate_skus' in self.fields:
            self.fields['alternate_skus'].required = False
            if self.instance and self.instance.pk:
                alternate_values = list(
                    self.instance.alternate_skus.order_by('kind', 'sku').values_list('sku', flat=True)
                )
                if alternate_values:
                    self.fields['alternate_skus'].initial = ", ".join(alternate_values)
        self._init_attribute_fields()
        self.attribute_fields = [self[name] for name in self.attribute_field_names]

    def _resolve_category(self):
        if not self.user:
            return None
        category_id = self.category_id_override
        if category_id in (None, ''):
            if self.is_bound:
                category_id = self.data.get('category') or self.data.get('category_id')
            else:
                category_id = self.instance.category_id
        try:
            category_id = int(category_id) if category_id else None
        except (TypeError, ValueError):
            category_id = None
        if not category_id:
            return None
        return Category.objects.filter(user=self.user, pk=category_id).first()

    def _get_category_chain(self, category):
        categories = []
        current = category
        while current:
            categories.append(current)
            current = current.parent
        return categories

    def _init_attribute_fields(self):
        category = self._resolve_category()
        if not category:
            return
        categories = self._get_category_chain(category)
        attribute_qs = (
            CategoryAttribute.objects.filter(user=self.user, category__in=categories, is_active=True)
            .select_related('category')
            .prefetch_related('options')
            .order_by('category__sort_order', 'sort_order', 'name')
        )
        existing_values = {}
        if self.instance and self.instance.pk:
            existing_values = {
                value.attribute_id: value
                for value in self.instance.attribute_values.select_related('option', 'attribute')
            }
        for attribute in attribute_qs:
            field_name = f"attr_{attribute.id}"
            self.attribute_field_names.append(field_name)
            self.attribute_map[field_name] = attribute
            if attribute.attribute_type == 'select':
                field = forms.ModelChoiceField(
                    queryset=attribute.options.filter(is_active=True).order_by('sort_order', 'value'),
                    required=False,
                )
                field.empty_label = '---------'
                existing = existing_values.get(attribute.id)
                if existing and existing.option_id:
                    field.initial = existing.option_id
            elif attribute.attribute_type == 'number':
                field = forms.DecimalField(
                    required=False,
                    max_digits=12,
                    decimal_places=4,
                )
                existing = existing_values.get(attribute.id)
                if existing and existing.value_number is not None:
                    field.initial = existing.value_number
            elif attribute.attribute_type == 'boolean':
                field = forms.NullBooleanField(required=False)
                existing = existing_values.get(attribute.id)
                if existing and existing.value_boolean is not None:
                    field.initial = existing.value_boolean
            else:
                field = forms.CharField(required=False)
                existing = existing_values.get(attribute.id)
                if existing and existing.value_text:
                    field.initial = existing.value_text
            label = attribute.name
            if attribute.value_unit:
                label = f"{label} ({attribute.value_unit})"
            field.label = label
            if attribute.description:
                field.help_text = attribute.description
            elif attribute.value_unit:
                field.help_text = f"Units: {attribute.value_unit}"
            field.widget.attrs.setdefault('data-attribute-id', str(attribute.id))
            options_text = ''
            if attribute.attribute_type == 'select':
                options_text = ', '.join(
                    option.value for option in attribute.options.filter(is_active=True).order_by('sort_order', 'value')
                )
            field.attribute_metadata = {
                'id': attribute.id,
                'name': attribute.name or '',
                'description': attribute.description or '',
                'value_unit': attribute.value_unit or '',
                'attribute_type': attribute.attribute_type or 'select',
                'category_id': attribute.category_id or '',
                'category_name': attribute.category.name if attribute.category else '',
                'is_filterable': attribute.is_filterable,
                'is_comparable': attribute.is_comparable,
                'is_active': attribute.is_active,
                'sort_order': attribute.sort_order if attribute.sort_order is not None else '',
                'options_text': options_text,
            }
            self.fields[field_name] = field

    def clean(self):
        cleaned_data = super().clean()
        brand = cleaned_data.get('brand')
        vehicle_model = cleaned_data.get('vehicle_model')
        if vehicle_model and vehicle_model.brand_id and brand and vehicle_model.brand_id != brand.id:
            self.add_error('vehicle_model', 'Selected model does not match the chosen brand.')
        alternate_skus = cleaned_data.get('alternate_skus') or []
        main_sku = (cleaned_data.get('sku') or self.instance.sku or '').strip()
        if main_sku:
            main_key = main_sku.casefold()
            if any(alt.casefold() == main_key for alt in alternate_skus):
                self.add_error('alternate_skus', 'Alternate SKUs cannot include the primary SKU.')
        return cleaned_data

    class Meta:
        model = Product
        exclude = ['user']
        labels = {
            'item_type': 'Item Type',
            'sku': 'Product SKU (optional)',
            'name': 'Product Name',
            'description': 'Product Description',
            'category': 'Category',
            'supplier': 'Supplier',
            'brand': 'Brand',
            'vehicle_model': 'Model',
            'vin_number': 'VIN Number',
            'cost_price': 'Cost Price',
            'sale_price': 'Sale Price',
            'margin': 'Margin',
            'promotion_price': 'Promotion Price',
            'core_price': 'Core Charge',
            'environmental_fee': 'Environmental Fee',
            'quantity_in_stock': 'Quantity in Stock',
            'reorder_level': 'Reorder Level',
            'image': 'Product Image',
            'is_published_to_store': 'Show on public storefront',
            'is_featured': 'Feature on storefront',
            'warranty_expiry_date': 'Warranty Expiry Date',
            'warranty_length': 'Warranty Length (days)',
            'location': 'Location',
        }
        help_texts = {
            'is_published_to_store': 'Publish this product for customers to see in your online store.',
            'promotion_price': 'Optional discounted price shown in the storefront.',
            'is_featured': 'Highlight this product in featured storefront sections.',
        }
        widgets = {
            'item_type': forms.Select(),
            'sku': forms.TextInput(attrs={'placeholder': 'Unique SKU identifier'}),
            'name': forms.TextInput(attrs={'placeholder': 'Name of the product'}),
            'description': forms.Textarea(attrs={'placeholder': 'Brief description of the product'}),
            'cost_price': forms.NumberInput(attrs={'placeholder': 'Cost price of the product'}),
            'sale_price': forms.NumberInput(attrs={'placeholder': 'Selling price of the product'}),
            'margin': forms.NumberInput(attrs={'placeholder': 'Margin (sale price minus cost price)', 'step': 'any'}),
            'promotion_price': forms.NumberInput(attrs={'placeholder': 'Promo price (optional)', 'step': 'any'}),
            'core_price': forms.NumberInput(attrs={'placeholder': 'Core charge (optional)', 'step': 'any'}),
            'environmental_fee': forms.NumberInput(attrs={'placeholder': 'Environmental fee (optional)', 'step': 'any'}),
            'quantity_in_stock': forms.NumberInput(attrs={'placeholder': 'Current stock quantity'}),
            'reorder_level': forms.NumberInput(attrs={'placeholder': 'Level at which to reorder stock'}),
            'warranty_expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'warranty_length': forms.NumberInput(attrs={'placeholder': 'Warranty length in days'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        return normalized

    def clean_sku(self):
        sku = self.cleaned_data.get('sku')
        if sku is None:
            return None
        normalized = sku.strip()
        if not normalized:
            return None
        if self.user:
            qs = Product.objects.filter(user=self.user, sku__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a product with this SKU.')
        return normalized

    def clean_alternate_skus(self):
        alternate_skus = _normalize_alternate_skus(self.cleaned_data.get('alternate_skus'))
        for sku in alternate_skus:
            if len(sku) > 100:
                raise forms.ValidationError('Alternate SKUs must be 100 characters or fewer.')
        return alternate_skus

    def save_attribute_values(self, product):
        if not product or not product.pk:
            return
        if not self.attribute_map:
            ProductAttributeValue.objects.filter(product=product).delete()
            return

        attribute_ids = [attribute.id for attribute in self.attribute_map.values()]
        ProductAttributeValue.objects.filter(product=product).exclude(attribute_id__in=attribute_ids).delete()

        for field_name, attribute in self.attribute_map.items():
            value = self.cleaned_data.get(field_name)
            existing = ProductAttributeValue.objects.filter(product=product, attribute=attribute).first()
            if attribute.attribute_type == 'select':
                if value:
                    if not existing:
                        existing = ProductAttributeValue(product=product, attribute=attribute)
                    existing.option = value
                    existing.value_text = ''
                    existing.value_number = None
                    existing.value_boolean = None
                    existing.save()
                elif existing:
                    existing.delete()
            elif attribute.attribute_type == 'number':
                if value is not None:
                    if not existing:
                        existing = ProductAttributeValue(product=product, attribute=attribute)
                    existing.option = None
                    existing.value_text = ''
                    existing.value_number = value
                    existing.value_boolean = None
                    existing.save()
                elif existing:
                    existing.delete()
            elif attribute.attribute_type == 'boolean':
                if value is not None:
                    if not existing:
                        existing = ProductAttributeValue(product=product, attribute=attribute)
                    existing.option = None
                    existing.value_text = ''
                    existing.value_number = None
                    existing.value_boolean = bool(value)
                    existing.save()
                elif existing:
                    existing.delete()
            else:
                if value:
                    if not existing:
                        existing = ProductAttributeValue(product=product, attribute=attribute)
                    existing.option = None
                    existing.value_text = value
                    existing.value_number = None
                    existing.value_boolean = None
                    existing.save()
                elif existing:
                    existing.delete()


class ProductAttributeForm(ProductForm):
    """Category + attribute-only form for editing product attributes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        keep_fields = {"category"}
        keep_fields.update(self.attribute_field_names)
        for field_name in list(self.fields.keys()):
            if field_name not in keep_fields:
                self.fields.pop(field_name)


class ProductInlineForm(forms.ModelForm):
    """Slimmed-down product form for inline editing in the product library."""

    alternate_skus = forms.CharField(
        required=False,
        label="Alternate / Interchange SKUs",
        help_text="Separate multiple SKUs with commas.",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Alternate SKUs (optional)",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.user = user
        super().__init__(*args, **kwargs)
        if getattr(self.instance, 'user_id', None):
            self.user = self.instance.user
        if self.user:
            self.fields['supplier'].queryset = Supplier.objects.filter(user=self.user).order_by('name')
            self.fields['category'].queryset = Category.objects.filter(user=self.user).order_by('name')
            if 'brand' in self.fields:
                self.fields['brand'].queryset = ProductBrand.objects.filter(user=self.user).order_by('sort_order', 'name')
            if 'vehicle_model' in self.fields:
                self.fields['vehicle_model'].queryset = ProductModel.objects.filter(user=self.user).order_by('sort_order', 'name')
            if 'vin_number' in self.fields:
                self.fields['vin_number'].queryset = ProductVin.objects.filter(user=self.user).order_by('sort_order', 'vin')
            locations = InventoryLocation.objects.filter(user=self.user).order_by('name')
            choices = [('', '---------')] + [(loc.name, loc.name) for loc in locations]
            self.fields['location'] = forms.ChoiceField(
                choices=choices,
                required=False,
                label='Location',
            )
            if self.instance and self.instance.location:
                self.fields['location'].initial = self.instance.location
        if 'sku' in self.fields:
            self.fields['sku'].required = False
        if 'sale_price' in self.fields:
            self.fields['sale_price'].required = False
        if 'core_price' in self.fields:
            self.fields['core_price'].required = False
        if 'environmental_fee' in self.fields:
            self.fields['environmental_fee'].required = False
        if 'alternate_skus' in self.fields:
            self.fields['alternate_skus'].required = False
            if self.instance and self.instance.pk:
                alternate_values = list(
                    self.instance.alternate_skus.order_by('kind', 'sku').values_list('sku', flat=True)
                )
                if alternate_values:
                    self.fields['alternate_skus'].initial = ", ".join(alternate_values)
        if 'category' in self.fields:
            self.fields['category'].required = False
        if 'supplier' in self.fields:
            self.fields['supplier'].required = False
        if 'image' in self.fields:
            self.fields['image'].required = False

    class Meta:
        model = Product
        fields = [
            'name',
            'sku',
            'description',
            'image',
            'category',
            'supplier',
            'brand',
            'vehicle_model',
            'vin_number',
            'cost_price',
            'sale_price',
            'core_price',
            'environmental_fee',
            'quantity_in_stock',
            'reorder_level',
            'item_type',
            'location',
        ]
        labels = {
            'name': 'Product Name',
            'sku': 'Product SKU',
            'description': 'Product Description',
            'image': 'Product Image',
            'category': 'Category',
            'supplier': 'Supplier',
            'brand': 'Brand',
            'vehicle_model': 'Model',
            'vin_number': 'VIN Number',
            'cost_price': 'Cost Price',
            'sale_price': 'Sale Price',
            'core_price': 'Core Charge',
            'environmental_fee': 'Environmental Fee',
            'quantity_in_stock': 'Quantity in Stock',
            'reorder_level': 'Reorder Level',
            'item_type': 'Item Type',
            'location': 'Location',
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        return normalized

    def clean_sku(self):
        sku = self.cleaned_data.get('sku')
        if sku is None:
            return None
        normalized = sku.strip()
        if not normalized:
            return None
        if self.user:
            qs = Product.objects.filter(user=self.user, sku__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a product with this SKU.')
        return normalized

    def clean_alternate_skus(self):
        alternate_skus = _normalize_alternate_skus(self.cleaned_data.get('alternate_skus'))
        for sku in alternate_skus:
            if len(sku) > 100:
                raise forms.ValidationError('Alternate SKUs must be 100 characters or fewer.')
        return alternate_skus

    def clean(self):
        cleaned_data = super().clean()
        brand = cleaned_data.get('brand')
        vehicle_model = cleaned_data.get('vehicle_model')
        if vehicle_model and vehicle_model.brand_id and brand and vehicle_model.brand_id != brand.id:
            self.add_error('vehicle_model', 'Selected model does not match the chosen brand.')
        alternate_skus = cleaned_data.get('alternate_skus') or []
        main_sku = (cleaned_data.get('sku') or self.instance.sku or '').strip()
        if main_sku:
            main_key = main_sku.casefold()
            if any(alt.casefold() == main_key for alt in alternate_skus):
                self.add_error('alternate_skus', 'Alternate SKUs cannot include the primary SKU.')
        return cleaned_data

class QuickProductCreateForm(forms.ModelForm):
    """Simplified product form for creating inventory items from expense entry."""

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.user = user
        super().__init__(*args, **kwargs)

        # Ensure consistent styling and predictable element IDs for modal usage.
        for name, field in self.fields.items():
            existing_classes = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = (existing_classes + ' form-control').strip()
            field.widget.attrs['id'] = f'quick_product_{name}'

        if user:
            self.fields['category'].queryset = Category.objects.filter(user=user).order_by('name')

        # Allow optional description and category when creating from an expense.
        self.fields['description'].required = False
        self.fields['category'].required = False
        if 'item_type' in self.fields:
            self.fields['item_type'].required = False

        # Provide helpful placeholders for commonly entered details.
        self.fields['name'].widget.attrs.setdefault('placeholder', 'Product name')
        self.fields['sku'].widget.attrs.setdefault('placeholder', 'SKU or part number (optional)')
        self.fields['description'].widget.attrs.setdefault('rows', 3)
        self.fields['cost_price'].widget.attrs.setdefault('placeholder', 'Cost price')
        self.fields['sale_price'].widget.attrs.setdefault('placeholder', 'Sale price')
        self.fields['sale_price'].required = False

    class Meta:
        model = Product
        fields = ['name', 'sku', 'description', 'category', 'item_type', 'cost_price', 'sale_price']
        labels = {
            'name': 'Product Name',
            'sku': 'SKU / Part Number',
            'description': 'Description',
            'category': 'Category',
            'item_type': 'Item Type',
            'cost_price': 'Cost Price',
            'sale_price': 'Sale Price',
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        normalized = name.strip()
        return normalized

    def clean_sku(self):
        sku = self.cleaned_data.get('sku')
        if sku in (None, ''):
            return None
        normalized = sku.strip()
        if not normalized:
            return None
        if self.user:
            qs = Product.objects.filter(user=self.user, sku__iexact=normalized)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('You already have a product with this SKU.')
        return normalized

class InventoryTransactionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            product_user_ids = get_product_stock_user_ids(user)
            self.fields['product'].queryset = Product.objects.filter(
                user__in=product_user_ids,
                item_type='inventory',
            )

    class Meta:
        model = InventoryTransaction
        fields = '__all__'
        labels = {
            'product': 'Product',
            'transaction_type': 'Transaction Type',
            'quantity': 'Quantity',
            'transaction_date': 'Transaction Date',
            'remarks': 'Remarks',
        }
        widgets = {
            'quantity': forms.NumberInput(attrs={'placeholder': 'Enter quantity'}),
            'transaction_date': forms.DateTimeInput(attrs={
                'placeholder': 'Date and time of transaction',
                'type': 'datetime-local'
            }),
            'remarks': forms.Textarea(attrs={'placeholder': 'Additional remarks (optional)'}),
        }


class DriverSettlementStatementForm(forms.ModelForm):
    class Meta:
        model = DriverSettlementStatement
        fields = ['driver', 'date_from', 'date_to']
        widgets = {
            'date_from': DateInput(),
            'date_to': DateInput(),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['driver'].queryset = Driver.objects.filter(user=user)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'driver',
            'date_from',
            'date_to',
            ButtonHolder(Submit('submit', 'Generate Report', css_class='btn btn-success'))
        )


class DriverSettlementActivityForm(forms.ModelForm):
    class Meta:
        model = DriverSettlementActivity
        fields = ['job', 'qty', 'rate', 'date', 'ticket', 'jobsite', 'truck']
        widgets = {
            'date': DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super(DriverSettlementActivityForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False  # This is useful if using an inline formset

DriverSettlementActivityFormSet = inlineformset_factory(
    DriverSettlementStatement,
    DriverSettlementActivity,
    form=DriverSettlementActivityForm,
    extra=0,
    can_delete=True
)

class GroupedEstimateForm(forms.ModelForm):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = GroupedEstimate
        fields = [
            'date', 'customer', 'po_number', 'vin_no', 'mileage', 'unit_no',
            'make_model', 'date_from', 'date_to', 'is_subscription', 'subscription_frequency',
            'tax_exempt', 'tax_exempt_reason'
        ]
        widgets = {
            'date': DateInput(attrs={'class': 'form-control'}),
            'po_number': forms.TextInput(attrs={'class': 'form-control'}),
            'date_from': DateInput(attrs={'class': 'form-control'}),
            'date_to': DateInput(attrs={'class': 'form-control'}),
            'vin_no': forms.TextInput(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_no': forms.TextInput(attrs={'class': 'form-control'}),
            'make_model': forms.TextInput(attrs={'class': 'form-control'}),
            'is_subscription': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'subscription_frequency': forms.Select(attrs={'class': 'form-control'}),
            'tax_exempt': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_tax_exempt'}),
            'tax_exempt_reason': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_tax_exempt_reason', 'list': 'tax-exemption-reasons'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(GroupedEstimateForm, self).__init__(*args, **kwargs)

        if self.user:
            business_user_ids = get_customer_user_ids(self.user)
            self.fields['customer'].queryset = Customer.objects.filter(user__in=business_user_ids)

        non_required_fields = ['po_number', 'vin_no', 'mileage', 'unit_no', 'make_model']
        for field in non_required_fields:
            if field in self.fields:
                self.fields[field].required = False

        if 'tax_exempt_reason' in self.fields:
            self.fields['tax_exempt_reason'].required = False

        self.fields['vin_no'].label = 'VIN Number'
        self.fields['mileage'].label = 'Mileage'
        self.fields['unit_no'].label = 'Unit Number'
        self.fields['make_model'].label = 'Make and Model'
        for field in ['date_from', 'date_to']:
            self.fields.pop(field, None)
        if 'date' in self.fields and not self.is_bound and not self.instance.pk:
            if not self.initial.get('date'):
                self.fields['date'].initial = timezone.localdate()

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Estimate Details',
                'date',
                'customer',
                'po_number',
                'vin_no',
                'mileage',
                'unit_no',
                'make_model',
                'date_from',
                'date_to',
                'is_subscription',
                'subscription_frequency',
                'tax_exempt',
                'tax_exempt_reason',
            ),
            ButtonHolder(
                Submit('submit', 'Save Estimate', css_class='btn btn-success')
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        is_subscription = cleaned_data.get('is_subscription')
        frequency = cleaned_data.get('subscription_frequency')
        if is_subscription and not frequency:
            self.add_error('subscription_frequency', 'Please select a frequency for subscription estimates.')
        return cleaned_data


class EstimateRecordForm(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        widget=forms.HiddenInput()
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = EstimateRecord
        fields = ['job', 'qty', 'rate', 'date', 'ticket', 'jobsite', 'truck', 'product', 'driver']
        widgets = {
            'job': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe labor/job performed',
            }),
            'date': DateInput(),
            'jobsite': forms.TextInput(attrs={'list': 'jobsite_list'}),
            'truck': forms.TextInput(attrs={'list': 'truck_list'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(EstimateRecordForm, self).__init__(*args, **kwargs)
        if user:
            product_user_ids = get_product_user_ids(user)
            self.fields['product'].queryset = Product.objects.filter(user__in=product_user_ids)
            drivers = Driver.objects.filter(user=user)
            if self.instance and self.instance.pk and self.instance.driver:
                drivers = (drivers | Driver.objects.filter(pk=self.instance.driver.pk)).distinct()
            self.fields['driver'].queryset = drivers

        self.fields['job'].label = 'Description'
        self.fields['qty'].label = 'Quantity'

        self.fields['rate'].label = 'Price'
        for field in ['date', 'ticket', 'jobsite', 'truck']:
            self.fields[field].required = False

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Div(Field('job'), css_class='col-12 col-md-6'),
                Div(Field('qty'), css_class='col-6 col-md-3'),
                Div(Field('rate'), css_class='col-6 col-md-3'),
            ),
            Field('product'),
            Field('driver')
        )

EstimateRecordFormSet = inlineformset_factory(
    GroupedEstimate,
    EstimateRecord,
    form=EstimateRecordForm,
    extra=1,
    can_delete=True
)

class MechanicForm(forms.ModelForm):
    register_portal = forms.BooleanField(
        required=False,
        label="Register for portal access",
    )
    portal_username = forms.CharField(required=False, label="Login Username")
    portal_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="Password",
    )
    class Meta:
        model = Mechanic
        fields = [
            'name',
            'phone',
            'email',
            'register_portal',
            'portal_username',
            'portal_password',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and getattr(self.instance, "portal_user", None):
            self.fields["portal_username"].initial = self.instance.portal_user.username
            self.fields["register_portal"].initial = True

# Simplified form for quickly adding a mechanic from the list view
class MechanicBasicForm(forms.ModelForm):
    class Meta:
        model = Mechanic
        fields = ["name", "phone", "email"]

# Sign up form used by mechanics when registering via an invite code
class MechanicSignupForm(UserCreationForm):
    name = forms.CharField(max_length=100, label="Full Name")
    phone = forms.CharField(max_length=20, required=False)
    email = forms.EmailField(required=False)
    signup_code = forms.CharField(max_length=32, label="Signup Code")

    class Meta:
        model = User
        fields = ["username", "password1", "password2"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email")
        if commit:
            user.save()
        return user

# forms.py

class WorkOrderForm(forms.ModelForm):
    road_service = forms.BooleanField(
        required=False,
        label="Road service",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    road_location = forms.CharField(
        required=False,
        label="Roadside location",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search or pin a location'}),
    )
    road_location_lat = forms.DecimalField(required=False, widget=forms.HiddenInput())
    road_location_lng = forms.DecimalField(required=False, widget=forms.HiddenInput())
    road_contact_phone = PhoneNumberField(
        required=False,
        label="Customer phone (optional)",
        widget=PhoneNumberWidget(attrs={'placeholder': 'Phone number'}),
    )

    mechanics = forms.ModelMultipleChoiceField(
        queryset=Mechanic.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '6'}),
        label='Assigned Mechanics',
        help_text='Choose one or more mechanics who should collaborate on this work order.',
    )

    class Meta:
        model = WorkOrder
        fields = [
            'scheduled_date', 'customer', 'vehicle', 'vehicle_vin', 'mileage',
            'unit_no', 'make_model', 'license_plate', 'description', 'status',
            'road_service', 'road_location', 'road_location_lat', 'road_location_lng', 'road_contact_phone',
        ]
        widgets = {
            'scheduled_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        # Filter the customer queryset
        business_user_ids = get_customer_user_ids(user)
        self.fields['customer'].queryset = Customer.objects.filter(user__in=business_user_ids)
        # Filter the mechanic queryset based on the logged in user
        mechanic_qs = Mechanic.objects.filter(user=user).order_by('name')
        self.fields['mechanics'].queryset = mechanic_qs
        self.fields['mechanics'].widget.attrs.setdefault('data-placeholder', 'Select mechanics')
        self.fields['vehicle'].queryset = Vehicle.objects.filter(customer__user__in=business_user_ids)
        self.fields['vehicle'].widget = forms.HiddenInput()
        self.fields['vehicle'].required = False

        for optional_field in ('vehicle_vin', 'mileage', 'unit_no', 'make_model', 'license_plate'):
            if optional_field in self.fields:
                self.fields[optional_field].required = False

        if self.instance and self.instance.pk:
            self.initial['vehicle'] = self.instance.vehicle_id
            self.initial['vehicle_vin'] = self.instance.vehicle_vin
            self.initial['mileage'] = self.instance.mileage
            self.initial['unit_no'] = self.instance.unit_no
            self.initial['make_model'] = self.instance.make_model
            self.initial['license_plate'] = self.instance.license_plate
            current_mechanics = self.instance.assignments.values_list('mechanic_id', flat=True)
            self.initial['mechanics'] = list(current_mechanics)
        else:
            self.initial.setdefault('mechanics', [])

        self._selected_mechanics = []

    @property
    def selected_mechanics(self):
        return list(self._selected_mechanics)

    def clean(self):
        cleaned_data = super().clean()
        # Some browsers submit multiple values for hidden inputs if the field
        # is rendered twice (e.g., via hidden_fields and manually). When this
        # happens Django keeps the last value which may be an empty string.
        # Recover the first non-empty selection so that vehicle data isn't lost.
        if not cleaned_data.get('vehicle') and hasattr(self.data, 'getlist'):
            field_name = self.add_prefix('vehicle')
            vehicle_qs = self.fields['vehicle'].queryset
            for raw_value in self.data.getlist(field_name):
                raw_value = (raw_value or '').strip()
                if not raw_value:
                    continue
                try:
                    vehicle_obj = vehicle_qs.filter(pk=raw_value).first()
                except (TypeError, ValueError):
                    continue
                if vehicle_obj:
                    cleaned_data['vehicle'] = vehicle_obj
                    break
        if not cleaned_data.get('road_service'):
            cleaned_data['road_location'] = ''
            cleaned_data['road_location_lat'] = None
            cleaned_data['road_location_lng'] = None
            cleaned_data['road_contact_phone'] = ''
        else:
            if not cleaned_data.get('road_contact_phone'):
                customer = cleaned_data.get('customer')
                if customer and customer.phone_number:
                    cleaned_data['road_contact_phone'] = validate_phone_number(customer.phone_number)
        return cleaned_data

    def _apply_vehicle_defaults(self, instance):
        """Ensure key vehicle snapshot fields mirror the selected vehicle."""
        vehicle = self.cleaned_data.get('vehicle')
        if not vehicle:
            return

        instance.vehicle = vehicle

        if not self.cleaned_data.get('vehicle_vin'):
            instance.vehicle_vin = vehicle.vin_number or None

        if not self.cleaned_data.get('unit_no'):
            instance.unit_no = vehicle.unit_number or None

        if not self.cleaned_data.get('make_model'):
            instance.make_model = vehicle.make_model or None

        if not self.cleaned_data.get('license_plate'):
            instance.license_plate = vehicle.license_plate or None

        mileage_value = self.cleaned_data.get('mileage')
        if (mileage_value is None or mileage_value == '') and vehicle.current_mileage is not None:
            instance.mileage = vehicle.current_mileage

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_vehicle_defaults(instance)
        if commit:
            instance.save()
        self._selected_mechanics = list(self.cleaned_data.get('mechanics') or [])
        return instance

    def save_m2m(self):
        """Assignments are managed manually in the view layer."""
        return




class WorkOrderRecordForm(forms.ModelForm):
    class Meta:
        model = WorkOrderRecord
        # Include product to capture parts added via modal (rendered as hidden input)
        fields = ['job', 'qty', 'rate', 'product']
        widgets = {
            'job': forms.Textarea(
                attrs={
                    'placeholder': 'Enter job description',
                    'class': 'form-control',
                    'rows': 3,
                }
            ),
            'qty': forms.NumberInput(attrs={'placeholder': 'Quantity', 'class': 'form-control'}),
            'rate': forms.NumberInput(attrs={'placeholder': 'Rate', 'class': 'form-control'}),
            'product': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if 'product' in self.fields:
            qs = Product.objects.all()
            if self.user:
                product_user_ids = get_product_user_ids(self.user)
                qs = qs.filter(user__in=product_user_ids)
            self.fields['product'].queryset = qs
            self.fields['product'].required = False

WorkOrderRecordFormSet = inlineformset_factory(
    WorkOrder,
    WorkOrderRecord,
    form=WorkOrderRecordForm,
    extra=0,
    can_delete=True
)

class ProductLineForm(forms.ModelForm):
    """Form for a single product line item within the WorkOrderRecord."""
    class Meta:
        model = WorkOrderRecord
        fields = ['product', 'qty']
        widgets = {
            'product': forms.Select(attrs={
                # Keep existing form-select for Bootstrap styling
                # Add searchable class for Select2 JS targeting
                "class": "form-select product-select product-select-searchable"
             }),
            'qty': forms.NumberInput(attrs={"class": "form-control product-quantity", "step": "any", "min": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user and 'product' in self.fields:
            product_user_ids = get_product_user_ids(user)
            self.fields['product'].queryset = Product.objects.filter(
                user__in=product_user_ids
            ).order_by('name')
            self.fields['product'].empty_label = "--- Select Product ---"
        self.fields['product'].required = False
        self.fields['qty'].required = False
        self.fields['product'].label = "Product"
        self.fields['qty'].label = "Quantity Used"

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not self.cleaned_data.get('DELETE') and self.cleaned_data.get('product'):
            selected_product = self.cleaned_data['product']
            instance.job = f"Part – {selected_product.name}"
            # Assign directly - sale_price should already be Decimal if model field is DecimalField
            instance.rate = selected_product.sale_price
        elif not self.cleaned_data.get('product'):
             instance.job = None
             instance.rate = None

        if commit:
            should_save = instance.product or (instance.pk and self.cleaned_data.get('DELETE'))
            if should_save:
                 instance.save()
            # (Optional logic for handling deselection/clearing of existing rows removed for simplicity)

        return instance

# --- Inline Formset Definition ---
ProductUsageRecordInlineFormSet = inlineformset_factory(
    WorkOrder,
    WorkOrderRecord,
    form=ProductLineForm,
    extra=1,
    can_delete=True,
    fk_name='work_order',
)

# Simplified form for mechanics without quantity field
class MechanicProductLineForm(ProductLineForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['qty'].initial = 1


MechanicProductUsageRecordInlineFormSet = inlineformset_factory(
    WorkOrder,
    WorkOrderRecord,
    form=MechanicProductLineForm,
    extra=1,
    can_delete=True,
    fk_name='work_order',
)


class WorkOrderReassignForm(forms.Form):
    instructions = forms.CharField(
        label="Updated Instructions",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "form-control",
                "placeholder": "Provide clear instructions for the mechanic to address before resubmitting.",
            }
        ),
    )


# --- Main Form for Mechanic ---
class MechanicWorkOrderForm(forms.ModelForm):
    """
    Form for the main details a mechanic fills (non-product/job lines).
    Includes optional vehicle details, notes, and submission status.
    """
    # Read-only field showing the original description
    description = forms.CharField(
        label="Owner's Description",
        required=False,
        widget=forms.Textarea(attrs={"readonly": "readonly", "rows": 3, "class": "form-control"})
    )

    # --- NEW: Optional Vehicle Detail Fields ---
    vehicle_vin = forms.CharField(
        label="Vehicle VIN",
        max_length=17,
        required=False, # Mechanic doesn't have to fill this
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter 17-digit VIN (Optional)"})
    )
    mileage = forms.FloatField( # Or DecimalField if model uses Decimal
        label="Mileage / Odometer",
        required=False, # Mechanic doesn't have to fill this
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "any", "placeholder": "Enter current mileage (Optional)"})
    )
    unit_no = forms.CharField(
        label="Unit Number / License Plate",
        max_length=64, # Match model field length
        required=False, # Mechanic doesn't have to fill this
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Unit # or License Plate (Optional)"})
    )
    make_model = forms.CharField(
        label="Make & Model",
        max_length=50, # Match model field length
        required=False, # Mechanic doesn't have to fill this
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter vehicle make and model (Optional)"})
    )
    # --- End NEW Fields ---

    # Fields for mechanic notes split into cause and correction
    cause = forms.CharField(
        label="Cause",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Describe the cause of the issue..."})
    )
    correction = forms.CharField(
        label="Correction",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "Describe the correction performed..."})
    )
    # Checkbox to mark the work order as completed
    submitted = forms.BooleanField(
        required=False,
        label="Mark as Completed",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )

    class Meta:
        model = WorkOrder
        # Add the new fields to the Meta fields list
        fields = [
            'vehicle',
            'vehicle_vin',
            'mileage',
            'unit_no',
            'make_model',
            'cause',
            'correction'
            # Note: 'description' is handled manually above, not via Meta instance handling
            # Note: 'submitted' is handled manually above, not part of the model fields directly saved here
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate the read-only description field from the instance if it exists
        if self.instance and self.instance.pk:
            self.initial["description"] = self.instance.description
            # Populate initial values for the new fields from the instance
            self.initial["vehicle"] = self.instance.vehicle_id
            self.initial["vehicle_vin"] = self.instance.vehicle_vin
            self.initial["mileage"] = self.instance.mileage
            self.initial["unit_no"] = self.instance.unit_no
            self.initial["make_model"] = self.instance.make_model
            self.initial["cause"] = self.instance.cause
            self.initial["correction"] = self.instance.correction

        # Ensure cause and correction are optional
        self.fields['cause'].required = False
        self.fields['correction'].required = False
        self.fields['vehicle'].widget = forms.HiddenInput()
        self.fields['vehicle'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('vehicle') and hasattr(self.data, 'getlist'):
            field_name = self.add_prefix('vehicle')
            vehicle_qs = self.fields['vehicle'].queryset
            for raw_value in self.data.getlist(field_name):
                raw_value = (raw_value or '').strip()
                if not raw_value:
                    continue
                try:
                    vehicle_obj = vehicle_qs.filter(pk=raw_value).first()
                except (TypeError, ValueError):
                    continue
                if vehicle_obj:
                    cleaned_data['vehicle'] = vehicle_obj
                    break
        return cleaned_data

    # Save method remains the same - it saves fields listed in Meta.fields
    def _apply_vehicle_defaults(self, instance):
        vehicle = self.cleaned_data.get('vehicle')
        if not vehicle:
            return

        instance.vehicle = vehicle

        if not self.cleaned_data.get('vehicle_vin'):
            instance.vehicle_vin = vehicle.vin_number or None

        if not self.cleaned_data.get('unit_no'):
            instance.unit_no = vehicle.unit_number or None

        if not self.cleaned_data.get('make_model'):
            instance.make_model = vehicle.make_model or None

        mileage_value = self.cleaned_data.get('mileage')
        if (mileage_value is None or mileage_value == '') and vehicle.current_mileage is not None:
            instance.mileage = vehicle.current_mileage

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_vehicle_defaults(instance)
        if commit:
            instance.save()
        return instance

LABOR_RATE = Decimal('100.00')
class JobLineForm(forms.ModelForm):
    """Form for a single job/labor line item within the WorkOrderRecord."""
    class Meta:
        model = WorkOrderRecord
        fields = ['job', 'qty'] # Only job description and quantity (hours)
        widgets = {
            'job': forms.Textarea(attrs={
                "class": "form-control job-description",
                "placeholder": "Describe labor/job performed",
                "rows": 3,
            }),
            'qty': forms.NumberInput(attrs={
                "class": "form-control job-quantity",
                "step": "any",
                "min": "0.01", # Use string for HTML attribute
                "placeholder": "Hours"
            }),
        }

    def __init__(self, *args, **kwargs):
        # user = kwargs.pop('user', None) # Not strictly needed here unless filtering jobs
        super().__init__(*args, **kwargs)
        self.fields['job'].label = "Job Description"
        self.fields['qty'].label = "Hours Worked"
        # Make required only if not deleting
        self.fields['job'].required = False
        self.fields['qty'].required = False


    def clean(self):
        cleaned_data = super().clean()
        is_deleted = cleaned_data.get('DELETE', False)
        job = cleaned_data.get('job')
        qty = cleaned_data.get('qty')

        # Require job and qty if the form is not marked for deletion and either field has a value
        if not is_deleted and (job or qty):
            if not job:
                self.add_error('job', 'Job description is required if hours are entered.')
            if not qty:
                self.add_error('qty', 'Hours are required if a job description is entered.')
            elif qty <= 0:
                 self.add_error('qty', 'Hours must be positive.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Ensure product is None and set the fixed rate for labor records
        instance.product = None
        # Fetch LABOR_RATE dynamically if needed, e.g., from profile/settings
        instance.rate = LABOR_RATE

        # Only save if it's a valid entry (has job and qty) or is being deleted
        should_save = (
            not self.cleaned_data.get('DELETE') and
            self.cleaned_data.get('job') and
            self.cleaned_data.get('qty') and self.cleaned_data['qty'] > 0
        ) or (instance.pk and self.cleaned_data.get('DELETE'))

        if commit and should_save:
            instance.save()
        elif commit and not should_save and instance.pk:
             # If it's an existing record that became invalid (e.g., qty cleared), delete it
             # Or decide if you want to keep invalid rows - deleting is cleaner
             print(f"Deleting invalid/cleared existing Job Record {instance.pk}")
             instance.delete()


        return instance

JobRecordInlineFormSet = inlineformset_factory(
    WorkOrder,
    WorkOrderRecord,
    form=JobLineForm,
    extra=1,
    can_delete=True,
    fk_name='work_order',
)

# --- NEW VEHICLE FORM ---
class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = [
            'unit_number',
            'vin_number',
            'license_plate',
            'make_model',
            'year',
            'status',
            'start_date_in_service',
            'assigned_to',
            'current_mileage',
        ] # Fields editable by the user

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # VIN is optional; allow saving vehicles with just Unit #.
        if 'vin_number' in self.fields:
            self.fields['vin_number'].required = False
        if 'unit_number' in self.fields:
            # Keep unit optional at the field level to avoid breaking edits of legacy rows,
            # but enforce "at least one identifier" in clean().
            self.fields['unit_number'].required = False

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select mb-2'
            else:
                field.widget.attrs['class'] = 'form-control mb-2' # Add some margin
            if field_name == 'vin_number' and self.instance and self.instance.pk:
                # Optionally make VIN readonly after creation if it shouldn't be changed
                # field.widget.attrs['readonly'] = True
                pass
            if field_name == 'start_date_in_service':
                field.widget.attrs['type'] = 'date'

    def clean(self):
        cleaned = super().clean()
        unit = (cleaned.get('unit_number') or '').strip()
        vin = (cleaned.get('vin_number') or '').strip()
        raw_unit = (self.data.get('unit_number') or self.data.get('unit_no') or '').strip()
        raw_vin = (self.data.get('vin_number') or self.data.get('vin_no') or '').strip()
        status = cleaned.get('status')

        # Normalize empty strings (especially important now that vin_number can be NULL)
        cleaned['unit_number'] = unit or None
        cleaned['vin_number'] = vin or None
        if not status:
            cleaned['status'] = self.instance.status or Vehicle.STATUS_ACTIVE

        if not cleaned.get('unit_number') and not cleaned.get('vin_number') and not raw_unit and not raw_vin:
            raise forms.ValidationError("Please enter at least a Unit Number or a VIN Number.")

        return cleaned



class VehicleMaintenanceTaskForm(forms.ModelForm):
    mileage_interval = forms.TypedChoiceField(
        choices=[],
        required=False,
        coerce=lambda value: int(value) if value not in (None, "") else None,
        empty_value=None,
        widget=forms.Select(attrs={'class': 'form-select mb-2'}),
        label='Mileage interval',
        help_text='Select how many kilometers between reminders.',
    )

    class Meta:
        model = VehicleMaintenanceTask
        fields = ['title', 'description', 'due_date', 'due_mileage', 'mileage_interval', 'priority']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control mb-2'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        interval_choices = [('', 'No mileage interval')]
        for value, label in VehicleMaintenanceTask.mileage_interval_choices():
            interval_choices.append((value, label))

        instance_value = getattr(self.instance, 'mileage_interval', None)
        if instance_value and instance_value not in [choice[0] for choice in interval_choices if choice[0] != '']:
            interval_choices.append((instance_value, f"Every {instance_value:,} km"))

        self.fields['mileage_interval'].choices = interval_choices

        default_field_class = 'form-control mb-2'
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select mb-2')
            else:
                field.widget.attrs.setdefault('class', default_field_class)


class CustomerPortalQuickMaintenanceForm(forms.ModelForm):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label='Vehicle',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = VehicleMaintenanceTask
        fields = ['vehicle', 'title', 'priority', 'due_date', 'description']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'title': 'Maintenance title',
            'priority': 'Priority',
            'due_date': 'Due date',
            'description': 'Notes (optional)',
        }

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        if customer is not None:
            self.fields['vehicle'].queryset = customer.vehicles.order_by(
                'unit_number',
                'make_model',
                'vin_number',
            )
            self.fields['vehicle'].label_from_instance = self._format_vehicle_label
        self.fields['vehicle'].empty_label = 'Select vehicle'
        self.fields['title'].widget.attrs.setdefault('class', 'form-control')
        self.fields['title'].widget.attrs.setdefault('placeholder', 'e.g. Brake inspection')
        self.fields['due_date'].widget.attrs.setdefault('class', 'form-control')
        self.fields['description'].widget.attrs.setdefault('class', 'form-control')
        self.fields['description'].widget.attrs.setdefault(
            'placeholder', 'Add any notes your team should see (optional)'
        )
        self.fields['priority'].widget.attrs.setdefault('class', 'form-select')
        self.fields['vehicle'].widget.attrs.setdefault('class', 'form-select')
        self.fields['priority'].initial = VehicleMaintenanceTask.PRIORITY_MEDIUM

    def _format_vehicle_label(self, vehicle):
        segments = []
        if vehicle.unit_number:
            segments.append(f"Unit {vehicle.unit_number}")
        if vehicle.vin_number:
            segments.append(f"VIN {vehicle.vin_number}")
        if segments:
            return " · ".join(segments)
        return "Vehicle"


class VehicleMaintenanceCompleteForm(forms.ModelForm):
    class Meta:
        model = VehicleMaintenanceTask
        fields = ['completed_date', 'actual_mileage', 'work_order', 'completion_notes']
        widgets = {
            'completed_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control mb-2'}),
            'completion_notes': forms.Textarea(attrs={'rows': 4, 'class': 'form-control mb-2'}),
        }

    def __init__(self, *args, vehicle=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control mb-2')
        if vehicle is not None:
            workorders = vehicle.work_orders.select_related('customer').order_by('-scheduled_date', '-id')
            self.fields['work_order'].queryset = workorders
        elif user is not None:
            self.fields['work_order'].queryset = WorkOrder.objects.filter(user=user).order_by('-scheduled_date')
        else:
            self.fields['work_order'].queryset = WorkOrder.objects.none()
        self.fields['work_order'].empty_label = 'Select work order (optional)'


class VehicleQuickWorkOrderForm(forms.Form):
    scheduled_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control mb-2'}),
    )
    mechanics = forms.ModelMultipleChoiceField(
        queryset=Mechanic.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select mb-2', 'size': 4}),
    )
    maintenance_task = forms.ModelChoiceField(
        queryset=VehicleMaintenanceTask.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select mb-2'}),
    )

    def __init__(self, *args, user=None, vehicle=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['mechanics'].queryset = Mechanic.objects.filter(user=user).order_by('name')
        else:
            self.fields['mechanics'].queryset = Mechanic.objects.none()
        self.fields['mechanics'].label = 'Assign mechanics'
        self.fields['mechanics'].help_text = 'Select one or more mechanics to assign.'
        if vehicle is not None:
            qs = vehicle.maintenance_tasks.filter(
                status__in=VehicleMaintenanceTask.ACTIVE_STATUSES,
                work_order__isnull=True,
            ).order_by('due_date', 'priority', 'title')
            self.fields['maintenance_task'].queryset = qs
        else:
            self.fields['maintenance_task'].queryset = VehicleMaintenanceTask.objects.none()
        self.fields['maintenance_task'].empty_label = 'No linked maintenance task'

    def clean_scheduled_date(self):
        value = self.cleaned_data.get('scheduled_date')
        if not value:
            return timezone.localdate()
        return value

    def clean_mechanics(self):
        mechanics = self.cleaned_data.get('mechanics')
        if not mechanics:
            raise forms.ValidationError('Please select at least one mechanic.')
        return mechanics

class FleetVehicleForm(forms.ModelForm):
    class Meta:
        model = FleetVehicle
        fields = ["truck_number", "make", "model", "year", "vin_number", "license_plate"]
        widgets = {
            "year": forms.NumberInput(attrs={"min": 1900, "max": 2100}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control mb-2"
        if self.user:
            self.instance.user = self.user


class MaintenanceRecordForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRecord
        fields = [
            "vehicle",
            "date",
            "description",
            "odometer_reading",
            "cost",
            "next_due",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "next_due": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control mb-2"
        if self.user:
            self.fields["vehicle"].queryset = FleetVehicle.objects.filter(user=self.user)


# ===============================
# Payroll Forms
# ===============================

class PayrollSettingsForm(forms.ModelForm):
    class Meta:
        model = PayrollSettings
        fields = [
            "pay_period_frequency",
            "period_anchor_date",
            "default_pay_date_offset_days",
            "auto_approve_timesheets",
            "overtime_enabled",
            "overtime_daily_enabled",
            "overtime_daily_threshold",
            "overtime_weekly_enabled",
            "overtime_weekly_threshold",
            "overtime_multiplier",
        ]
        widgets = {
            "period_anchor_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "default_pay_date_offset_days": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "pay_period_frequency": forms.Select(attrs={"class": "form-select"}),
            "auto_approve_timesheets": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "overtime_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "overtime_daily_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "overtime_weekly_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "overtime_daily_threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "overtime_weekly_threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "overtime_multiplier": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "1"}),
        }


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "mechanic",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "status",
            "hire_date",
            "termination_date",
            "hourly_rate",
            "notes",
        ]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "termination_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["mechanic"].queryset = Mechanic.objects.filter(user=user).order_by("name")
        else:
            self.fields["mechanic"].queryset = Mechanic.objects.none()
        self.fields["mechanic"].required = False
        self.fields["mechanic"].widget.attrs.setdefault("class", "form-select")

        for field_name in ("first_name", "last_name", "email", "phone", "hourly_rate"):
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.setdefault("class", "form-control")


class EmployeeTaxProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeeTaxProfile
        fields = [
            "province",
            "federal_claim_amount",
            "provincial_claim_amount",
            "additional_withholding",
            "cpp_exempt",
            "cpp2_exempt",
            "ei_exempt",
        ]
        widgets = {
            "province": forms.Select(attrs={"class": "form-select"}),
            "federal_claim_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "provincial_claim_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "additional_withholding": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


class EmployeeRecurringDeductionForm(forms.ModelForm):
    class Meta:
        model = EmployeeRecurringDeduction
        fields = [
            "name",
            "amount",
            "is_pre_tax",
            "is_employee_contribution",
            "is_employer_contribution",
            "active",
        ]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "name" in self.fields:
            self.fields["name"].widget.attrs.setdefault("class", "form-control")


class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = ["name", "start_time", "end_time", "notes", "active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class TimesheetForm(forms.ModelForm):
    class Meta:
        model = Timesheet
        fields = [
            "employee",
            "period_start",
            "period_end",
            "status",
            "notes",
        ]
        widgets = {
            "employee": forms.Select(attrs={"class": "form-select"}),
            "period_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "period_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["employee"].queryset = Employee.objects.filter(user=user).order_by("first_name", "last_name")
        else:
            self.fields["employee"].queryset = Employee.objects.none()

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("period_start")
        end = cleaned.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "Period end must be on or after period start.")
        return cleaned


class TimeEntryForm(forms.ModelForm):
    class Meta:
        model = TimeEntry
        fields = ["work_date", "start_time", "end_time", "hours", "notes"]
        widgets = {
            "work_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "readonly": "readonly"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "hours" in self.fields:
            self.fields["hours"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned

        work_date = cleaned.get("work_date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        hours = cleaned.get("hours")
        notes = cleaned.get("notes")

        has_data = any([work_date, start_time, end_time, notes, hours])
        if not has_data:
            return cleaned

        if start_time or end_time:
            if not start_time or not end_time:
                self.add_error("start_time", "Start and finish times are required.")
                self.add_error("end_time", "Start and finish times are required.")
            elif work_date:
                start_dt = datetime.datetime.combine(work_date, start_time)
                end_dt = datetime.datetime.combine(work_date, end_time)
                if end_dt < start_dt:
                    end_dt += datetime.timedelta(days=1)
                diff_hours = (end_dt - start_dt).total_seconds() / 3600
                cleaned["hours"] = Decimal(diff_hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif hours in (None, Decimal("0.00")):
            self.add_error("hours", "Hours are required when no times are provided.")

        return cleaned

TimeEntryFormSet = inlineformset_factory(
    Timesheet,
    TimeEntry,
    form=TimeEntryForm,
    extra=1,
    can_delete=True,
)


class PayrollRunForm(forms.ModelForm):
    class Meta:
        model = PayrollRun
        fields = ["period_start", "period_end", "pay_date", "notes"]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "period_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "pay_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }


class PayrollTaxYearForm(forms.ModelForm):
    class Meta:
        model = PayrollTaxYear
        fields = [
            "year",
            "cpp_rate",
            "cpp_basic_exemption",
            "cpp_max_pensionable",
            "cpp2_rate",
            "cpp2_max_pensionable",
            "ei_rate",
            "ei_max_insurable",
            "ei_employer_multiplier",
            "federal_basic_personal_amount",
        ]
        widgets = {
            "year": forms.NumberInput(attrs={"class": "form-control"}),
            "cpp_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
            "cpp_basic_exemption": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "cpp_max_pensionable": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "cpp2_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
            "cpp2_max_pensionable": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "ei_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
            "ei_max_insurable": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "ei_employer_multiplier": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
            "federal_basic_personal_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


class PayrollProvinceTaxSettingForm(forms.ModelForm):
    class Meta:
        model = PayrollProvinceTaxSetting
        fields = ["province", "basic_personal_amount"]
        widgets = {
            "province": forms.Select(attrs={"class": "form-select"}),
            "basic_personal_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


class PayrollTaxBracketForm(forms.ModelForm):
    class Meta:
        model = PayrollTaxBracket
        fields = ["jurisdiction", "bracket_min", "bracket_max", "rate"]
        widgets = {
            "jurisdiction": forms.Select(attrs={"class": "form-select"}),
            "bracket_min": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "bracket_max": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
        }


class PayrollEmployerTaxForm(forms.ModelForm):
    class Meta:
        model = PayrollEmployerTax
        fields = ["province", "name", "rate", "threshold", "max_amount", "applies_to_all"]
        widgets = {
            "province": forms.Select(attrs={"class": "form-select"}),
            "rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001"}),
            "threshold": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "max_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


# ===============================
# Public-facing Forms
# ===============================

class PublicBookingForm(forms.ModelForm):
    preferred_datetime = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )

    class Meta:
        model = PublicBooking
        fields = [
            "full_name", "email", "phone", "company",
            "service_type", "pickup_location", "dropoff_location",
            "preferred_datetime", "notes"
        ]


class QuickBookingForm(forms.ModelForm):
    """Minimal public booking form for fast scheduling."""
    preferred_date = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={"type": "date"})
    )
    preferred_time = forms.TimeField(
        required=True,
        widget=forms.TimeInput(attrs={"type": "time"})
    )

    class Meta:
        model = PublicBooking
        fields = [
            "full_name", "email", "phone", "service_type",
        ]

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        phone = cleaned_data.get("phone")
        if not email and not phone:
            raise forms.ValidationError("Please provide at least one contact method: email or phone.")
        return cleaned_data

class EmergencyRequestForm(forms.ModelForm):
    class Meta:
        model = EmergencyRequest
        fields = [
            "full_name", "phone", "email", "issue_type",
            "location", "description"
        ]


class PublicContactForm(forms.ModelForm):
    class Meta:
        model = PublicContactMessage
        fields = ["full_name", "email", "phone", "message"]


class PortalContactForm(forms.ModelForm):
    class Meta:
        model = PublicContactMessage
        fields = [
            "full_name",
            "email",
            "phone",
            "message_type",
            "reference_code",
            "subject",
            "message",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "message_type": forms.Select(attrs={"class": "form-select"}),
            "reference_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional reference"}),
            "subject": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional subject"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].required = False
        self.fields["reference_code"].required = False
        self.fields["subject"].required = False
        self.fields["message_type"].label = "Topic"
        self.fields["reference_code"].label = "Reference ID"
        self.fields["subject"].label = "Subject"

class BusinessBookingSettingsForm(forms.ModelForm):
    class Meta:
        model = BusinessBookingSettings
        fields = ["start_time", "end_time", "slot_interval_minutes"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "slot_interval_minutes": forms.NumberInput(attrs={"min": 5, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slot_interval_minutes"].help_text = "How many minutes each appointment slot should cover."

    def clean_slot_interval_minutes(self):
        value = self.cleaned_data.get("slot_interval_minutes")
        if value is None or value <= 0:
            raise forms.ValidationError("Please enter a positive slot interval in minutes.")
        if value > 12 * 60:
            raise forms.ValidationError("Slot interval cannot exceed 12 hours.")
        return value

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        if start and end and end <= start:
            raise forms.ValidationError("Closing time must be after opening time.")
        return cleaned


class QuickBooksSettingsForm(forms.ModelForm):
    class Meta:
        model = QuickBooksSettings
        fields = [
            "integration_type",
            "client_id",
            "client_secret",
            "realm_id",
            "redirect_uri",
            "environment",
            "refresh_token",
            "desktop_company_name",
            "auto_sync_enabled",
        ]
        widgets = {
            "integration_type": forms.Select(attrs={"class": "form-select"}),
            "client_id": forms.PasswordInput(
                attrs={"class": "form-control", "autocomplete": "off"},
                render_value=True,
            ),
            "client_secret": forms.PasswordInput(
                attrs={"class": "form-control", "autocomplete": "off"},
                render_value=True,
            ),
            "realm_id": forms.PasswordInput(
                attrs={"class": "form-control", "autocomplete": "off"},
                render_value=True,
            ),
            "redirect_uri": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "environment": forms.Select(attrs={"class": "form-select"}),
            "refresh_token": forms.PasswordInput(
                attrs={"class": "form-control", "autocomplete": "off"},
                render_value=True,
            ),
            "desktop_company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "My QuickBooks Company"}
            ),
            "auto_sync_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "integration_type": "Integration type",
            "client_id": "Client ID",
            "client_secret": "Client Secret",
            "realm_id": "Realm (Company) ID",
            "redirect_uri": "Redirect URI",
            "environment": "Environment",
            "refresh_token": "Refresh Token",
            "desktop_company_name": "QuickBooks Desktop company name",
            "auto_sync_enabled": "Automatically sync invoices",
        }
        help_texts = {
            "refresh_token": "Paste the refresh token provided by the QuickBooks Developer portal.",
            "redirect_uri": "Optional if you are using the default redirect URI configured in the app.",
            "desktop_company_name": "Used to match records exchanged with QuickBooks Desktop.",
            "auto_sync_enabled": "When enabled, invoices will be synchronized automatically by scheduled jobs.",
        }

    def clean_refresh_token(self):
        token = self.cleaned_data.get("refresh_token")
        return token.strip() if token else token

    def clean_realm_id(self):
        realm_id = self.cleaned_data.get("realm_id")
        return realm_id.strip() if realm_id else realm_id

    def clean(self):
        cleaned = super().clean()
        integration_type = cleaned.get("integration_type") or QuickBooksSettings.INTEGRATION_ONLINE

        if integration_type == QuickBooksSettings.INTEGRATION_ONLINE:
            required_fields = ["client_id", "client_secret", "realm_id"]
            missing = [field for field in required_fields if not cleaned.get(field)]
            if missing:
                raise forms.ValidationError("Please complete all required QuickBooks credentials.")
            if not cleaned.get("refresh_token"):
                raise forms.ValidationError("A refresh token is required to communicate with QuickBooks Online.")
        else:
            if not cleaned.get("desktop_company_name"):
                raise forms.ValidationError("Please provide the QuickBooks Desktop company name.")
            # Ensure OAuth-specific fields are blanked when switching to desktop for clarity.
            for field in ("client_id", "client_secret", "realm_id", "refresh_token"):
                if not cleaned.get(field):
                    cleaned[field] = ""
        return cleaned


class BankingIntegrationSettingsForm(forms.ModelForm):
    class Meta:
        model = BankingIntegrationSettings
        fields = ["enabled", "require_review", "auto_sync_enabled"]
        widgets = {
            "enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "require_review": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "auto_sync_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "enabled": "Enable Flinks banking integration",
            "require_review": "Require approval before creating expenses",
            "auto_sync_enabled": "Sync transactions automatically",
        }
        help_texts = {
            "enabled": "Turn this on to allow connected bank accounts to sync transactions.",
            "require_review": "When enabled, transactions stay in the review queue until approved.",
            "auto_sync_enabled": "Allow background sync jobs to pull new transactions.",
        }


class BusinessHolidayForm(forms.ModelForm):
    class Meta:
        model = BusinessHoliday
        fields = ["date", "reason", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "reason": forms.TextInput(attrs={"class": "form-control", "placeholder": "Reason visible to customers"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control", "placeholder": "Internal notes (optional)"}),
        }

    def clean_date(self):
        target = self.cleaned_data.get("date")
        if target and BusinessHoliday.objects.filter(date=target).exists():
            raise forms.ValidationError("A holiday for this date already exists.")
        return target
