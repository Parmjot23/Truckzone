# admin.py (Updated)

from django.contrib import admin
from django.urls import path
import time
from django.template.response import TemplateResponse
from django.utils.html import format_html
from .models import (
    Mechanic, WorkOrder, WorkOrderRecord, Customer, ExpenseRecord, IncomeRecord, InvoiceDetail, IncomeRecord2, GroupedInvoice,
    Profile, PendingInvoice, PaidInvoice, MechExpense, MechExpenseItem, Payment, Category,
    Supplier, SupplierCredit, SupplierCreditItem, CustomerCredit, CustomerCreditItem, SupplierCheque, SupplierChequeLine, BusinessBankAccount,
    Product, InventoryTransaction, Driver, GroupedEstimate, EstimateRecord, WorkOrderAssignment, Vehicle, JobHistory,
    VehicleMaintenanceTask, FleetVehicle, MaintenanceRecord, QuickBooksSettings, ActivityLog, Service, CloverConnection,
    BankingIntegrationSettings, BankConnection, BankTransaction, PayrollSettings, Employee, EmployeeTaxProfile,
    EmployeeRecurringDeduction, Timesheet, TimeEntry, PayrollRun, PayStub, PayStubLineItem, PayrollTaxYear,
    PayrollProvinceTaxSetting, StorefrontHeroShowcase, StorefrontHeroShowcaseItem, StorefrontHeroPackage, StorefrontMessageBanner,
    PayrollTaxBracket, PayrollEmployerTax, ConnectedBusinessGroup
)
from .forms import (
    ExpenseForm, IncomeForm, GroupedInvoiceForm, IncomeRecord2Form,
    MechExpenseForm, MechExpenseItemForm
)
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.urls import reverse # Import reverse
from django.utils.html import format_html


# Customer Admin (No direct user link assumed in model, so no user filter/column)
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'total_amount_display', 'total_paid_display', 'total_balance_due')
    search_fields = ('name', 'email') # Added search fields

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Annotations moved here for clarity and efficiency
        qs = qs.annotate(
            _total_amount=Coalesce(Sum('invoices__total_amount'), Value(0), output_field=DecimalField()),
            _total_paid=Coalesce(Sum('invoices__payments__amount'), Value(0), output_field=DecimalField()),
        )
        return qs

    # Use the annotated fields directly
    def total_amount_display(self, obj):
        return CustomAdmin.format_currency(obj._total_amount) # Use formatter
    total_amount_display.admin_order_field = '_total_amount'
    total_amount_display.short_description = 'Total Amount'

    def total_paid_display(self, obj):
        return CustomAdmin.format_currency(obj._total_paid) # Use formatter
    total_paid_display.admin_order_field = '_total_paid'
    total_paid_display.short_description = 'Total Paid'

    def total_balance_due(self, obj):
        # Ensure values are treated as Decimal or float for subtraction
        total_amount = obj._total_amount if obj._total_amount is not None else 0
        total_paid = obj._total_paid if obj._total_paid is not None else 0
        balance = total_amount - total_paid
        return CustomAdmin.format_currency(balance) # Use formatter
    total_balance_due.short_description = 'Total Balance Due'
    # Note: Cannot easily sort by calculated balance without further annotation


@admin.register(ConnectedBusinessGroup)
class ConnectedBusinessGroupAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "share_customers",
        "share_products",
        "share_product_stock",
        "member_count",
        "updated_at",
    )
    list_filter = ("share_customers", "share_products", "share_product_stock")
    search_fields = ("name",)
    filter_horizontal = ("members",)

    def member_count(self, obj):
        return obj.members.count()

    member_count.short_description = "Members"


# Profile Inline for User Admin
class ProfileInline(admin.StackedInline):
    model = Profile
    fk_name = 'user'
    can_delete = False
    verbose_name_plural = 'Profile'
    readonly_fields = ('company_logo_display',)

    def company_logo_display(self, instance):
        if instance.company_logo:
            # Use format_html for safety
            return format_html('<img src="{}" style="max-width: 100px; height: auto;" />', instance.company_logo.url)
        return 'No logo'
    # company_logo_display.allow_tags = True # Deprecated in newer Django versions, format_html handles it
    company_logo_display.short_description = 'Company Logo'


class ConnectedBusinessGroupMembershipInline(admin.TabularInline):
    model = ConnectedBusinessGroup.members.through
    fk_name = "user"
    extra = 0
    verbose_name = "Connected business group"
    verbose_name_plural = "Connected business groups"
    raw_id_fields = ("connectedbusinessgroup",)


# User Admin with Profile Inline
class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline, ConnectedBusinessGroupMembershipInline)
    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'get_company_name',
        'connected_group_names',
    ) # Added company name
    list_filter = BaseUserAdmin.list_filter + ('profile__is_business_admin', 'profile__admin_approved')

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('connected_business_groups')

    # Method to display company name from profile
    def get_company_name(self, obj):
        # Check if profile exists
        if hasattr(obj, 'profile') and obj.profile:
            return obj.profile.company_name
        return "N/A"
    get_company_name.short_description = 'Company Name'

    def connected_group_names(self, obj):
        groups = list(obj.connected_business_groups.all())
        if not groups:
            return "-"
        names = [group.name or f"Group #{group.pk}" for group in groups]
        return ", ".join(names)
    connected_group_names.short_description = "Connected Groups"

# Base Custom Admin with formatting and common logic
class CustomAdmin(admin.ModelAdmin):
    """Base Admin class with currency formatting and user filtering logic."""

    @staticmethod
    def format_currency(value):
        """Formats a numeric value as currency."""
        if value is None or value == '':
             return "$0.00" # Or return "N/A" or an empty string if preferred
        try:
            # Ensure value is numeric before formatting
            numeric_value = DecimalField().to_python(value)
            return "${:,.2f}".format(numeric_value)
        except (ValueError, TypeError):
            return "Invalid Value" # Handle cases where conversion fails

    def get_queryset(self, request):
        """Filters queryset to show only logged-in user's data unless superuser."""
        qs = super().get_queryset(request)
        # Check if the model has a 'user' field directly
        user_field_direct = hasattr(self.model, 'user')
        # Check for indirect user links (adjust paths as needed per model)
        user_field_indirect_mech = hasattr(self.model, 'mech_expense') and hasattr(MechExpense, 'user')
        user_field_indirect_grouped = hasattr(self.model, 'grouped_invoice') and hasattr(GroupedInvoice, 'user')
        user_field_indirect_payment = hasattr(self.model, 'invoice') and hasattr(GroupedInvoice, 'user') # Assuming Payment.invoice links to GroupedInvoice

        if request.user.is_superuser:
            return qs # Superuser sees all

        # Apply filter based on how user is linked
        if user_field_direct:
             return qs.filter(user=request.user)
        elif user_field_indirect_mech:
             return qs.filter(mech_expense__user=request.user)
        elif user_field_indirect_grouped:
             return qs.filter(grouped_invoice__user=request.user)
        elif user_field_indirect_payment:
             # Careful: This assumes Payment.invoice ALWAYS links to GroupedInvoice
             # Might need adjustment if Payment can link to other invoice types
             return qs.filter(invoice__user=request.user)
        else:
             # If model doesn't seem linked to a user in expected ways, show all (or raise error?)
             # This might apply to models like Category, Supplier etc. if registered with CustomAdmin
             return qs


    def get_list_filter(self, request):
        """Adds 'user' to list_filter for superusers if applicable."""
        filters = list(super().get_list_filter(request))
        user_filter_added = False

        # Define potential user lookup paths for filtering
        user_paths = {
            'direct': 'user',
            'mech': 'mech_expense__user',
            'grouped': 'grouped_invoice__user',
            'payment': 'invoice__user', # Assuming Payment.invoice links to GroupedInvoice
        }

        # Determine the correct user path for the current model
        user_path = None
        if hasattr(self.model, 'user'):
            user_path = user_paths['direct']
        elif hasattr(self.model, 'mech_expense') and hasattr(MechExpense, 'user'):
            user_path = user_paths['mech']
        elif hasattr(self.model, 'grouped_invoice') and hasattr(GroupedInvoice, 'user'):
            user_path = user_paths['grouped']
        elif hasattr(self.model, 'invoice') and hasattr(GroupedInvoice, 'user'): # For Payment
            user_path = user_paths['payment']


        if request.user.is_superuser and user_path:
            if user_path not in filters:
                filters.append(user_path)
                user_filter_added = True

        # If this admin class has its own specific list_filter tuple defined, use it as base
        # Otherwise, use the filters inherited from super()
        base_filters = list(getattr(self, 'list_filter', []))
        if request.user.is_superuser and user_path:
             if user_path not in base_filters:
                 base_filters.append(user_path)
             return tuple(base_filters) # Return as tuple as expected by Django Admin
        elif hasattr(self, 'list_filter'):
             return tuple(base_filters) # Return specific filters if defined
        else:
             # If superuser filter wasn't added and no specific filters, return super's filters
             return tuple(filters) if user_filter_added else super().get_list_filter(request)


    def get_list_display(self, request):
        """Adds 'user' or related user lookup to list_display for superusers."""
        list_display = list(super().get_list_display(request))

        # Determine the attribute/method name to display the user
        user_display_attr = None
        if hasattr(self.model, 'user'):
            user_display_attr = 'user'
        elif hasattr(self, 'get_user'): # Check if a custom 'get_user' method exists
             user_display_attr = 'get_user'
        # Add more conditions if user is linked differently in other models

        if request.user.is_superuser and user_display_attr:
            if user_display_attr not in list_display:
                # Insert user column typically after the first column (e.g., ID or date)
                list_display.insert(1, user_display_attr)

        return tuple(list_display)

    def get_form(self, request, obj=None, **kwargs):
        """Passes the user to the form if needed."""
        form = super().get_form(request, obj, **kwargs)
        # Pass user to form if form expects it (check form implementations)
        if hasattr(form, 'user'):
            form.user = request.user
        if hasattr(form, 'current_user'):
             form.current_user = request.user
        return form

    def save_model(self, request, obj, form, change):
        """Sets the user automatically if it's not set (for direct user links)."""
        # Check if the object has a 'user' field and if it's not already set
        if hasattr(obj, 'user') and not getattr(obj, 'user_id', None):
            # Ensure we don't overwrite if user is explicitly set in the form (e.g., by superuser)
            if 'user' not in form.cleaned_data or not form.cleaned_data['user']:
                 obj.user = request.user
        super().save_model(request, obj, form, change)

    # Generic method to get user, adaptable in subclasses if needed
    def get_user(self, obj):
         """Generic method to display user; override in subclasses for indirect links."""
         if hasattr(obj, 'user'):
             return obj.user
         # Add specific implementations in subclasses like MechExpenseItemAdmin, IncomeRecord2Admin etc.
         return "N/A" # Default if user cannot be determined directly
    get_user.short_description = 'User'
    # Add admin_order_field if direct user field exists
    if hasattr(GroupedInvoice, 'user'): # Example check
        get_user.admin_order_field = 'user'


# Custom action to mark pending invoices as paid
def mark_as_paid(modeladmin, request, queryset):
    """Action to mark selected PendingInvoices as paid and move associated records."""
    invoices_marked = 0
    already_paid = []

    for pending_invoice in queryset.select_related('grouped_invoice'): # Optimize query
        # Check if it's already conceptually paid (maybe is_paid flag or exists in PaidInvoice)
        if PaidInvoice.objects.filter(grouped_invoice=pending_invoice.grouped_invoice).exists():
             already_paid.append(pending_invoice.grouped_invoice.invoice_number)
             continue # Skip if already processed

        # Option 1: If PendingInvoice has an is_paid flag (as in original code)
        # pending_invoice.is_paid = True
        # pending_invoice.save()

        # Option 2: Move to PaidInvoice and delete PendingInvoice (more robust state mgmt)
        paid_invoice, created = PaidInvoice.objects.get_or_create(
            grouped_invoice=pending_invoice.grouped_invoice
            # Copy other relevant fields if PaidInvoice duplicates them
        )

        if created:
            # Re-associate related IncomeRecord2 items if they point to PendingInvoice
            # This depends heavily on your model structure. The original code updated
            # IncomeRecord2 based on grouped_invoice, which seems more logical.
            # Let's assume IncomeRecord2 primarily links via grouped_invoice.
            # If IncomeRecord2 *also* has a direct FK to PendingInvoice/PaidInvoice, update that:

            # Example if IncomeRecord2 has FKs 'pending_invoice' and 'paid_invoice':
            # jobs = IncomeRecord2.objects.filter(pending_invoice=pending_invoice)
            # for job in jobs:
            #     job.pending_invoice = None
            #     job.paid_invoice = paid_invoice
            #     job.save()

            # Delete the pending invoice record after successful processing
            pending_invoice.delete()
            invoices_marked += 1
        else:
             # This case means it was already in PaidInvoice, handle similarly to already_paid
             already_paid.append(pending_invoice.grouped_invoice.invoice_number)
             # Optionally delete the redundant PendingInvoice entry if it shouldn't exist
             # pending_invoice.delete()


    if invoices_marked:
        modeladmin.message_user(request, f"{invoices_marked} selected invoices have been marked as paid.")
    if already_paid:
         modeladmin.message_user(
             request,
             f"Invoices {', '.join(already_paid)} were already marked as paid or processed.",
             level='warning' # Use warning or info
         )

mark_as_paid.short_description = "Mark selected invoices as paid"


# Admin classes inheriting from CustomAdmin
# They inherit get_queryset, get_list_filter, get_list_display modifications

class ExpenseRecordAdmin(CustomAdmin):
    form = ExpenseForm
    # list_display will be dynamically modified by CustomAdmin.get_list_display for superuser
    list_display = ('date', 'format_fuel', 'format_plates', 'format_wsib', 'format_repairs',
                    'format_parking', 'format_wash', 'format_def_fluid', 'format_insurance',
                    'format_total', 'format_tax_paid')
    search_fields = ('user__username', 'date', 'fuel', 'plates', 'wsib', 'repairs', 'parking', 'wash', 'def_fluid', 'insurance') # Added user
    # list_filter is handled by CustomAdmin.get_list_filter
    list_filter = ('date',) # Base filters for all users

    # Formatting methods
    def format_fuel(self, obj): return self.format_currency(obj.fuel)
    format_fuel.short_description = 'Fuel'
    # ... other format methods ...
    def format_plates(self, obj): return self.format_currency(obj.plates)
    format_plates.short_description = 'Plates'
    def format_wsib(self, obj): return self.format_currency(obj.wsib)
    format_wsib.short_description = 'WSIB'
    def format_repairs(self, obj): return self.format_currency(obj.repairs)
    format_repairs.short_description = 'Repairs'
    def format_parking(self, obj): return self.format_currency(obj.parking)
    format_parking.short_description = 'Parking'
    def format_wash(self, obj): return self.format_currency(obj.wash)
    format_wash.short_description = 'Wash'
    def format_def_fluid(self, obj): return self.format_currency(obj.def_fluid)
    format_def_fluid.short_description = 'DEF Fluid'
    def format_insurance(self, obj): return self.format_currency(obj.insurance)
    format_insurance.short_description = 'Insurance'
    def format_total(self, obj): return self.format_currency(obj.total)
    format_total.short_description = 'Total'
    def format_tax_paid(self, obj): return self.format_currency(obj.tax_paid)
    format_tax_paid.short_description = 'Tax Paid'

    # No need to override get_queryset, get_form, save_model - handled by CustomAdmin


class MechExpenseItemInline(admin.TabularInline):
    model = MechExpenseItem
    form = MechExpenseItemForm
    extra = 1
    # readonly_fields = ('amount',) # Consider making amount readonly if calculated


class MechExpenseAdmin(CustomAdmin):
    form = MechExpenseForm
    list_display = ('date', 'vendor', 'format_total_amount', 'view_items_link') # User added dynamically
    search_fields = ('user__username', 'vendor', 'date')
    list_filter = ('date', 'vendor') # Base filters
    inlines = [MechExpenseItemInline]

    def format_total_amount(self, obj):
        total_amount_including_tax, _ = obj.calculate_totals() # Ignoring total_tax here
        return self.format_currency(total_amount_including_tax)
    format_total_amount.short_description = 'Total amount (incl. tax)'

    def view_items_link(self, obj):
        # Use reverse for URL generation if possible, but direct path is okay too
        url = f"/admin/{self.model._meta.app_label}/{self.model._meta.model_name}/{obj.pk}/change/"
        return format_html('<a href="{}">View Items</a>', url)
    view_items_link.short_description = 'Items'
    view_items_link.allow_tags = True # Still needed for older Django? format_html is preferred

    # get_urls and view_items remain the same
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:object_id>/items/', self.admin_site.admin_view(self.view_items), name=f'{self.model._meta.app_label}_{self.model._meta.model_name}_items'),
        ]
        return custom_urls + urls

    def view_items(self, request, object_id):
        # Use get_object_or_404 for robustness
        from django.shortcuts import get_object_or_404
        mech_expense = get_object_or_404(self.model, pk=object_id)

        # Check permissions (redundant if get_queryset is correct, but good practice)
        if not request.user.is_superuser and mech_expense.user != request.user:
             from django.core.exceptions import PermissionDenied
             raise PermissionDenied

        items = MechExpenseItem.objects.filter(mech_expense=mech_expense)
        context = dict(
            self.admin_site.each_context(request),
            title=f"Items for Mech Expense {mech_expense}",
            opts=self.model._meta, # Pass model metadata
            mech_expense=mech_expense,
            items=items,
            app_label=self.model._meta.app_label,
        )
        # Consider using a more specific template or reusing the change form view structure
        return TemplateResponse(request, "admin/mech_expense/view_items.html", context) # Example template path


class MechExpenseItemAdmin(CustomAdmin):
    form = MechExpenseItemForm
    # User access is via mech_expense.user
    list_display = ('mech_expense', 'part_no', 'description', 'qty', 'format_price', 'format_amount') # User added dynamically by get_user
    search_fields = ('mech_expense__user__username', 'mech_expense__vendor', 'part_no', 'description') # Added user search
    # list_filter handled by CustomAdmin, uses 'mech_expense__user'
    list_filter = ('mech_expense__vendor',) # Base filters

    # Override get_user for indirect lookup
    def get_user(self, obj):
         return obj.mech_expense.user if obj.mech_expense else None
    get_user.short_description = 'User'
    get_user.admin_order_field = 'mech_expense__user'

    def format_price(self, obj): return self.format_currency(obj.price)
    format_price.short_description = 'Price'

    def format_amount(self, obj): return self.format_currency(obj.amount)
    format_amount.short_description = 'Amount'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Filter dropdown for MechExpense based on user (if not superuser)
        if db_field.name == 'mech_expense' and not request.user.is_superuser:
            kwargs["queryset"] = MechExpense.objects.filter(user=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # save_model handled by CustomAdmin (doesn't need override here)


class IncomeRecordAdmin(CustomAdmin):
    # This model seems deprecated in favor of IncomeRecord2/GroupedInvoice?
    # If still used and has a direct 'user' FK:
    form = IncomeForm
    list_display = ('date', 'ticket', 'jobsite', 'truck', 'job', 'format_qty', 'format_rate', 'format_amount', 'format_tax_collected') # User added dynamically
    search_fields = ('user__username', 'date', 'ticket', 'jobsite', 'truck', 'job') # Added user search
    list_filter = ('date', 'jobsite', 'truck', 'job') # Base filters

    def format_qty(self, obj): return self.format_currency(obj.qty) # Assuming qty is currency-like? Adjust if not.
    format_qty.short_description = 'Quantity'

    def format_rate(self, obj): return self.format_currency(obj.rate)
    format_rate.short_description = 'Rate'

    def format_amount(self, obj): return self.format_currency(obj.amount)
    format_amount.short_description = 'Amount'

    def format_tax_collected(self, obj): return self.format_currency(obj.tax_collected)
    format_tax_collected.short_description = 'Tax Collected'

    # total_amount method seems redundant if amount is present? Removed.


class IncomeRecord2Inline(admin.TabularInline):
    model = IncomeRecord2
    form = IncomeRecord2Form
    extra = 1
    # Add readonly fields if needed, e.g., readonly_fields = ('amount', 'tax_collected')


class IncomeRecord2Admin(CustomAdmin):
    # Linked to user via GroupedInvoice
    form = IncomeRecord2Form
    list_display = (
        'get_date', 'get_bill_to', 'get_invoice_number', 'job', 'driver',
        'format_qty', 'format_rate', 'format_amount', 'format_tax_collected'
    ) # User added dynamically via get_user
    search_fields = (
        'grouped_invoice__user__username', # Added user search
        'grouped_invoice__date', 'grouped_invoice__bill_to', 'grouped_invoice__invoice_number',
        'job', 'driver__name' # Search by driver name
    )
    # list_filter handled by CustomAdmin, uses 'grouped_invoice__user'
    list_filter = ('grouped_invoice__date', 'grouped_invoice__bill_to', 'job', 'driver') # Base filters

    # Override get_user for indirect lookup
    def get_user(self, obj):
         return obj.grouped_invoice.user if obj.grouped_invoice else None
    get_user.short_description = 'User'
    get_user.admin_order_field = 'grouped_invoice__user'

    # Methods to get data from related GroupedInvoice
    def get_date(self, obj): return obj.grouped_invoice.date if obj.grouped_invoice else None
    get_date.admin_order_field = 'grouped_invoice__date'
    get_date.short_description = 'Date'

    def get_bill_to(self, obj): return obj.grouped_invoice.bill_to if obj.grouped_invoice else None
    get_bill_to.admin_order_field = 'grouped_invoice__bill_to'
    get_bill_to.short_description = 'Bill To'

    def get_invoice_number(self, obj): return obj.grouped_invoice.invoice_number if obj.grouped_invoice else None
    get_invoice_number.admin_order_field = 'grouped_invoice__invoice_number'
    get_invoice_number.short_description = 'Invoice Number'

    # Formatting methods
    def format_qty(self, obj): return self.format_currency(obj.qty) # Adjust if qty isn't currency
    format_qty.short_description = 'Quantity'
    def format_rate(self, obj): return self.format_currency(obj.rate)
    format_rate.short_description = 'Rate'
    def format_amount(self, obj): return self.format_currency(obj.amount)
    format_amount.short_description = 'Amount'
    def format_tax_collected(self, obj): return self.format_currency(obj.tax_collected)
    format_tax_collected.short_description = 'Tax Collected'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Filter GroupedInvoice dropdown
        if db_field.name == 'grouped_invoice' and not request.user.is_superuser:
            kwargs["queryset"] = GroupedInvoice.objects.filter(user=request.user)
        # Filter Driver dropdown (if you want to restrict drivers per user, needs a user link on Driver)
        # if db_field.name == 'driver' and not request.user.is_superuser:
        #    kwargs["queryset"] = Driver.objects.filter(...) # Add logic if drivers are user-specific
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class GroupedInvoiceAdmin(CustomAdmin):
    # Has a direct user link
    form = GroupedInvoiceForm
    list_display = ('date', 'bill_to', 'invoice_number', 'driver', 'vin_no', 'format_mileage', 'unit_no', 'format_total_amount', 'view_jobs_link') # User added dynamically
    search_fields = ('user__username', 'date', 'bill_to', 'invoice_number', 'driver__name', 'vin_no', 'unit_no') # Added user, driver name search
    list_filter = ('date', 'bill_to', 'driver') # Base filters
    inlines = [IncomeRecord2Inline]
    readonly_fields = ('total_amount',) # Make total_amount readonly as it's calculated

    def format_mileage(self, obj):
        # Mileage likely isn't currency, format as number
        return "{:,.0f}".format(obj.mileage) if obj.mileage is not None else "N/A"
    format_mileage.short_description = 'Mileage'

    def format_total_amount(self, obj):
        # total_amount is likely calculated on the model or via annotation
        return self.format_currency(obj.total_amount)
    format_total_amount.short_description = 'Total amount (incl. tax)'
    # format_total_amount.admin_order_field = 'total_amount' # Enable sorting if 'total_amount' is a db field or annotation

    def view_jobs_link(self, obj):
        # Link to the change page which shows the inline items
        url = f"/admin/{self.model._meta.app_label}/{self.model._meta.model_name}/{obj.pk}/change/"
        return format_html('<a href="{}">View Details / Jobs</a>', url)
    view_jobs_link.short_description = 'Details / Jobs'

    # Remove get_urls and view_jobs - viewing jobs is handled by the standard change view with inlines
    # If a separate read-only view is still desired, the original code can be kept/adapted.


class InvoiceDetailAdmin(CustomAdmin):
    # Assumes 'user' is a direct ForeignKey
    list_display = ('bill_to',) # User added dynamically
    search_fields = ('user__username', 'bill_to') # Added user search
    list_filter = ('bill_to',) # Base filters
    # get_queryset handled by CustomAdmin


class PendingInvoiceAdmin(CustomAdmin):
    # Linked via GroupedInvoice
    # list_display includes fields derived from GroupedInvoice
    list_display = ('get_date', 'get_bill_to', 'get_invoice_number', 'get_total_amount', 'is_paid', 'view_jobs_link') # User added dynamically via get_user
    search_fields = ('grouped_invoice__user__username', 'grouped_invoice__date', 'grouped_invoice__bill_to', 'grouped_invoice__invoice_number', 'is_paid') # Added user search
    list_filter = ('is_paid', 'grouped_invoice__date', 'grouped_invoice__bill_to') # Base filters
    actions = [mark_as_paid]
    # Define readonly fields - likely most fields if it's just a status marker
    readonly_fields = ('grouped_invoice', 'is_paid') # Make grouped_invoice readonly after creation

    # Override get_user for indirect lookup
    def get_user(self, obj):
         return obj.grouped_invoice.user if obj.grouped_invoice else None
    get_user.short_description = 'User'
    get_user.admin_order_field = 'grouped_invoice__user'

    # Methods to get data from related GroupedInvoice
    def get_date(self, obj): return obj.grouped_invoice.date if obj.grouped_invoice else None
    get_date.admin_order_field = 'grouped_invoice__date'
    get_date.short_description = 'Date'

    def get_bill_to(self, obj): return obj.grouped_invoice.bill_to if obj.grouped_invoice else None
    get_bill_to.admin_order_field = 'grouped_invoice__bill_to'
    get_bill_to.short_description = 'Bill To'

    def get_invoice_number(self, obj): return obj.grouped_invoice.invoice_number if obj.grouped_invoice else None
    get_invoice_number.admin_order_field = 'grouped_invoice__invoice_number'
    get_invoice_number.short_description = 'Invoice Number'

    def get_total_amount(self, obj):
        return self.format_currency(obj.grouped_invoice.total_amount if obj.grouped_invoice else 0)
    get_total_amount.short_description = 'Total Amount'
    # get_total_amount.admin_order_field = 'grouped_invoice__total_amount' # If sorting needed

    def view_jobs_link(self, obj):
        # Link to the related GroupedInvoice change page to see jobs
        if obj.grouped_invoice:
             url = f"/admin/{GroupedInvoice._meta.app_label}/{GroupedInvoice._meta.model_name}/{obj.grouped_invoice.pk}/change/"
             return format_html('<a href="{}">View Associated Invoice Jobs</a>', url)
        return "No associated invoice"
    view_jobs_link.short_description = 'Jobs (on Invoice)'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Filter GroupedInvoice dropdown if it's editable
        if db_field.name == 'grouped_invoice' and not request.user.is_superuser:
            # Optionally, filter only invoices that aren't already Pending or Paid
            kwargs["queryset"] = GroupedInvoice.objects.filter(user=request.user)
                                        #.exclude(paidinvoice__isnull=False)
                                        #.exclude(pendinginvoice__isnull=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # Remove get_urls and view_jobs - link goes to GroupedInvoice admin


class PaidInvoiceAdmin(CustomAdmin):
    # Similar structure to PendingInvoiceAdmin
    list_display = ('get_date', 'get_bill_to', 'get_invoice_number', 'get_total_amount', 'view_jobs_link') # User added dynamically via get_user
    search_fields = ('grouped_invoice__user__username', 'grouped_invoice__date', 'grouped_invoice__bill_to', 'grouped_invoice__invoice_number') # Added user search
    list_filter = ('grouped_invoice__date', 'grouped_invoice__bill_to') # Base filters
    readonly_fields = ('grouped_invoice',) # Should be readonly after creation

    # Override get_user for indirect lookup
    def get_user(self, obj):
         return obj.grouped_invoice.user if obj.grouped_invoice else None
    get_user.short_description = 'User'
    get_user.admin_order_field = 'grouped_invoice__user'

    # Methods to get data from related GroupedInvoice (same as PendingInvoiceAdmin)
    def get_date(self, obj): return obj.grouped_invoice.date if obj.grouped_invoice else None
    get_date.admin_order_field = 'grouped_invoice__date'
    get_date.short_description = 'Date'

    def get_bill_to(self, obj): return obj.grouped_invoice.bill_to if obj.grouped_invoice else None
    get_bill_to.admin_order_field = 'grouped_invoice__bill_to'
    get_bill_to.short_description = 'Bill To'

    def get_invoice_number(self, obj): return obj.grouped_invoice.invoice_number if obj.grouped_invoice else None
    get_invoice_number.admin_order_field = 'grouped_invoice__invoice_number'
    get_invoice_number.short_description = 'Invoice Number'

    def get_total_amount(self, obj):
        return self.format_currency(obj.grouped_invoice.total_amount if obj.grouped_invoice else 0)
    get_total_amount.short_description = 'Total Amount'
    # get_total_amount.admin_order_field = 'grouped_invoice__total_amount' # If sorting needed

    def view_jobs_link(self, obj):
         # Link to the related GroupedInvoice change page to see jobs
         if obj.grouped_invoice:
             url = f"/admin/{GroupedInvoice._meta.app_label}/{GroupedInvoice._meta.model_name}/{obj.grouped_invoice.pk}/change/"
             return format_html('<a href="{}">View Associated Invoice Jobs</a>', url)
         return "No associated invoice"
    view_jobs_link.short_description = 'Jobs (on Invoice)'

    def has_add_permission(self, request):
         # Usually PaidInvoices are created via action, not directly
         return False

    def has_change_permission(self, request, obj=None):
         # Maybe disallow changes after creation?
         return True # Or False depending on workflow

    def has_delete_permission(self, request, obj=None):
        # Consider if paid invoices should be deletable
        return True # Or False

    # Remove get_urls and view_jobs - link goes to GroupedInvoice admin


# PaymentInline for use in other models (e.g., GroupedInvoice if needed)
class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 1
    readonly_fields = ('date',) # Payment date should default to now and be readonly?
    fields = ('date', 'amount', 'method', 'notes')
    can_delete = True


@admin.register(Payment)
class PaymentAdmin(CustomAdmin):
    # Assuming Payment.invoice links to GroupedInvoice (which has user)
    list_display = ('invoice', 'date', 'format_amount', 'method', 'notes') # User added dynamically via get_user
    list_filter = ('method', 'date') # Base filters
    search_fields = ('invoice__user__username', 'invoice__invoice_number', 'notes', 'method') # Added user search
    date_hierarchy = 'date'
    ordering = ('-date',)
    # Make invoice field searchable/filterable if it links usefully
    autocomplete_fields = ['invoice'] # If GroupedInvoiceAdmin has search_fields

    # Override get_user for indirect lookup via invoice -> user
    def get_user(self, obj):
         # Check if invoice exists and has a user attribute
         if obj.invoice and hasattr(obj.invoice, 'user'):
             return obj.invoice.user
         return None
    get_user.short_description = 'User'
    get_user.admin_order_field = 'invoice__user'

    def format_amount(self, obj):
        return self.format_currency(obj.amount)
    format_amount.short_description = "Amount"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Filter Invoice dropdown based on user
        if db_field.name == 'invoice' and not request.user.is_superuser:
            # Assuming 'invoice' FK points to GroupedInvoice
            kwargs["queryset"] = GroupedInvoice.objects.filter(user=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # save_model is tricky here if Payment doesn't have a direct user field.
    # The user context is derived from the selected Invoice.


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin): # Inherit directly from ModelAdmin if no user filtering needed
    list_display = ('name', 'gst_hst_number', 'pay_gst_hst', 'license_number', 'phone', 'email')
    search_fields = ('name', 'gst_hst_number', 'phone', 'email')
    list_filter = ('pay_gst_hst',) # Add filter if useful

@admin.register(GroupedEstimate)
class GroupedEstimateAdmin(admin.ModelAdmin):
    list_display = ('estimate_number', 'date', 'bill_to', 'total_amount')
    search_fields = ('estimate_number', 'bill_to')

@admin.register(EstimateRecord)
class EstimateRecordAdmin(admin.ModelAdmin):
    list_display = ('grouped_estimate', 'job', 'amount')
    search_fields = ('grouped_estimate__estimate_number', 'job')

@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'scheduled_date', 'list_mechanics', 'status', 'customer')
    search_fields = ('id', 'description', 'customer__name')
    list_filter = ('status', 'scheduled_date')

    def list_mechanics(self, obj):
        names = [
            assignment.mechanic.name
            for assignment in obj.assignments.select_related('mechanic')
        ]
        return ', '.join(names) if names else "No Mechanics Assigned"

    list_mechanics.short_description = 'Mechanics'


@admin.register(WorkOrderRecord)
class WorkOrderRecordAdmin(admin.ModelAdmin):
    list_display = ('work_order', 'job', 'qty', 'rate', 'amount')
    search_fields = ('job',)

@admin.register(WorkOrderAssignment)
class WorkOrderAssignmentAdmin(admin.ModelAdmin):
    list_display = ('workorder', 'mechanic', 'assignment_token', 'submitted', 'date_assigned')
    search_fields = ('workorder__id', 'mechanic__name')

@admin.register(Mechanic)
class MechanicAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email')
    search_fields = ('name',)
    
# ... (after other admin class definitions like CustomerAdmin, UserAdmin, CustomAdmin) ...

# --- Admin classes for new models: Vehicle and JobHistory ---

@admin.register(Vehicle)
class VehicleAdmin(CustomAdmin):
    list_display = (
        'vin_number',
        'unit_number',
        'make_model',
        'current_mileage',
        'customer',
        'display_customer_user',
        'view_job_history_link'  # New column for the button/link
    )
    search_fields = ('vin_number', 'unit_number', 'make_model', 'customer__name', 'customer__user__username')
    list_filter = ('make_model', 'customer__name')
    autocomplete_fields = ['customer']

    def display_customer_user(self, obj):
        if obj.customer and obj.customer.user:
            return obj.customer.user.username
        return "N/A"
    display_customer_user.short_description = 'User (from Customer)'
    display_customer_user.admin_order_field = 'customer__user__username'

    def view_job_history_link(self, obj):
        # 'obj' here is a Vehicle instance
        # We need to construct a URL to the JobHistory changelist,
        # filtered by this vehicle's ID.
        # The query parameter for filtering will be 'vehicle__id__exact'
        job_history_url = reverse('admin:accounts_jobhistory_changelist') # Make sure 'accounts' is your app_label
        
        # Add a filter for the current vehicle's ID
        # The filter query parameter should be `vehicle__id__exact` if your JobHistory.vehicle field is named 'vehicle'
        # Or simply `vehicle_id` might work too. Let's use the more explicit one.
        return format_html(
            '<a class="button" href="{}?vehicle__id__exact={}">View History ({})</a>',
            job_history_url,
            obj.pk,
            obj.job_history.count() # Display count of jobs
        )
    view_job_history_link.short_description = 'Job History'
    view_job_history_link.allow_tags = True # Still needed for older Django versions, but format_html is preferred




@admin.register(VehicleMaintenanceTask)
class VehicleMaintenanceTaskAdmin(CustomAdmin):
    list_display = (
        'title',
        'vehicle',
        'status',
        'due_date',
        'due_mileage',
        'mileage_interval',
        'priority',
        'completed_date',
    )
    list_filter = ('status', 'priority', 'due_date', 'completed_date')
    search_fields = (
        'title',
        'vehicle__vin_number',
        'vehicle__unit_number',
        'vehicle__customer__name',
    )
    autocomplete_fields = ['vehicle', 'work_order', 'user']
    readonly_fields = ('created_at', 'updated_at')

@admin.register(JobHistory)
class JobHistoryAdmin(CustomAdmin):
    list_display = (
        'job_date',
        'vehicle_link', # This already links to the vehicle
        'short_description',
        'invoice_link',
        'service_cost_formatted',
        'tax_amount_formatted',
        'total_job_cost_formatted',
        'display_job_user'
    )
    search_fields = (
        'vehicle__vin_number', 
        'vehicle__unit_number', 
        'description', 
        'invoice__invoice_number', 
        'source_income_record__job', 
        'vehicle__customer__user__username'
    )
    # Add 'vehicle' to list_filter for easy filtering in the JobHistory view
    list_filter = ('job_date', 'vehicle__make_model', 'vehicle') # Added 'vehicle'
    autocomplete_fields = ['vehicle', 'invoice', 'source_income_record']
    readonly_fields = ('total_job_cost',)
    date_hierarchy = 'job_date'

    def vehicle_link(self, obj):
        if obj.vehicle:
            link = reverse(f"admin:{obj.vehicle._meta.app_label}_{obj.vehicle._meta.model_name}_change", args=[obj.vehicle.pk])
            return format_html('<a href="{}">{}</a>', link, obj.vehicle)
        return "N/A"
    vehicle_link.short_description = 'Vehicle'
    vehicle_link.admin_order_field = 'vehicle'

    def invoice_link(self, obj):
        if obj.invoice:
            link = reverse(f"admin:{obj.invoice._meta.app_label}_{obj.invoice._meta.model_name}_change", args=[obj.invoice.pk])
            return format_html('<a href="{}">{}</a>', link, obj.invoice.invoice_number)
        return "N/A"
    invoice_link.short_description = 'Invoice'
    invoice_link.admin_order_field = 'invoice'
    
    def short_description(self, obj):
        return (obj.description[:75] + '...') if len(obj.description) > 75 else obj.description
    short_description.short_description = 'Description'

    def service_cost_formatted(self, obj): return self.format_currency(obj.service_cost)
    service_cost_formatted.short_description = 'Service Cost'
    service_cost_formatted.admin_order_field = 'service_cost'

    def tax_amount_formatted(self, obj): return self.format_currency(obj.tax_amount)
    tax_amount_formatted.short_description = 'Tax'
    tax_amount_formatted.admin_order_field = 'tax_amount'

    def total_job_cost_formatted(self, obj): return self.format_currency(obj.total_job_cost)
    total_job_cost_formatted.short_description = 'Total Cost'
    total_job_cost_formatted.admin_order_field = 'total_job_cost'

    def display_job_user(self, obj):
        if obj.vehicle and obj.vehicle.customer and obj.vehicle.customer.user:
            return obj.vehicle.customer.user.username
        elif obj.invoice and obj.invoice.user:
            return obj.invoice.user.username
        return "N/A"
    display_job_user.short_description = 'User (from Vehicle/Invoice)'
    display_job_user.admin_order_field = 'vehicle__customer__user__username'

# --- Admin classes for fleet maintenance ---

@admin.register(FleetVehicle)
class FleetVehicleAdmin(CustomAdmin):
    list_display = ('make', 'model', 'year', 'vin_number', 'license_plate', 'truck_number', 'display_user')
    search_fields = ('vin_number', 'license_plate', 'truck_number', 'make', 'model')
    list_filter = ('make', 'model')
    autocomplete_fields = ['user']

    def display_user(self, obj):
        return obj.user.username if obj.user else 'N/A'
    display_user.short_description = 'User'


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(CustomAdmin):
    list_display = ('vehicle', 'date', 'short_description', 'cost')
    search_fields = ('vehicle__vin_number', 'description')
    list_filter = ('vehicle', 'date')
    autocomplete_fields = ['vehicle']
    date_hierarchy = 'date'

    def short_description(self, obj):
        return (obj.description[:75] + '...') if len(obj.description) > 75 else obj.description
    short_description.short_description = 'Description'


@admin.register(Service)
class ServiceAdmin(CustomAdmin):
    list_display = (
        'name',
        'job_name',
        'fixed_hours',
        'fixed_rate',
        'due_after_kilometers',
        'due_after_months',
        'user',
        'is_active',
        'updated_at',
    )
    list_filter = ('is_active', 'job_name__name')
    search_fields = (
        'name',
        'job_name__name',
        'user__username',
        'user__profile__company_name',
    )
    ordering = ('job_name__name', 'name')


@admin.register(QuickBooksSettings)
class QuickBooksSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'integration_type', 'environment', 'auto_sync_enabled', 'last_synced_at')
    list_filter = ('integration_type', 'environment', 'auto_sync_enabled')
    search_fields = ('user__username', 'user__email', 'realm_id', 'desktop_company_name')
    readonly_fields = (
        'last_synced_at',
        'last_sync_status',
        'access_token',
        'access_token_expires_at',
        'created_at',
        'updated_at',
    )


@admin.register(CloverConnection)
class CloverConnectionAdmin(admin.ModelAdmin):
    list_display = ('user', 'merchant_id', 'env', 'sync_pos_payments', 'sync_online_payments', 'last_sync_at')
    list_filter = ('env', 'sync_pos_payments', 'sync_online_payments')
    search_fields = ('user__username', 'user__email', 'merchant_id')
    readonly_fields = ('created_at', 'updated_at', 'last_sync_at', 'token_expires_at')


@admin.register(BankingIntegrationSettings)
class BankingIntegrationSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider', 'enabled', 'auto_sync_enabled', 'require_review', 'last_synced_at')
    list_filter = ('provider', 'enabled', 'auto_sync_enabled', 'require_review')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at', 'last_synced_at')


@admin.register(BankConnection)
class BankConnectionAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider', 'institution_name', 'connection_id', 'status', 'env', 'last_sync_at')
    list_filter = ('provider', 'status', 'env')
    search_fields = ('user__username', 'user__email', 'institution_name', 'connection_id')
    readonly_fields = ('created_at', 'updated_at', 'last_sync_at')


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider', 'posted_at', 'merchant_name', 'amount', 'status', 'linked_expense')
    list_filter = ('provider', 'status')
    search_fields = ('user__username', 'merchant_name', 'description', 'external_id')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'business', 'actor', 'action', 'object_type', 'object_id')
    list_filter = ('action', 'object_type', 'business')
    search_fields = ('description', 'actor__username', 'business__username', 'object_id')
    readonly_fields = ('created_at', 'metadata')
    ordering = ('-created_at',)


# ... (rest of your admin classes) ...


# Unregister default User admin first
admin.site.unregister(User)
# Register User with the custom UserAdmin (includes Profile inline)
admin.site.register(User, UserAdmin)

# Register models with their respective custom admin classes
admin.site.register(ExpenseRecord, ExpenseRecordAdmin)
admin.site.register(IncomeRecord, IncomeRecordAdmin) # If still in use
admin.site.register(InvoiceDetail, InvoiceDetailAdmin)
admin.site.register(IncomeRecord2, IncomeRecord2Admin)
admin.site.register(GroupedInvoice, GroupedInvoiceAdmin)
admin.site.register(PendingInvoice, PendingInvoiceAdmin)
admin.site.register(PaidInvoice, PaidInvoiceAdmin)
admin.site.register(MechExpense, MechExpenseAdmin)
admin.site.register(MechExpenseItem, MechExpenseItemAdmin)
admin.site.register(SupplierCredit)
admin.site.register(SupplierCreditItem)
admin.site.register(CustomerCredit)
admin.site.register(CustomerCreditItem)
admin.site.register(SupplierCheque)
admin.site.register(SupplierChequeLine)
admin.site.register(BusinessBankAccount)

# Payroll models
admin.site.register(PayrollSettings)
admin.site.register(Employee)
admin.site.register(EmployeeTaxProfile)
admin.site.register(EmployeeRecurringDeduction)
admin.site.register(Timesheet)
admin.site.register(TimeEntry)
admin.site.register(PayrollRun)
admin.site.register(PayStub)
admin.site.register(PayStubLineItem)
admin.site.register(PayrollTaxYear)
admin.site.register(PayrollProvinceTaxSetting)
admin.site.register(PayrollTaxBracket)
admin.site.register(PayrollEmployerTax)

# Register models without specific complex admin views (will use default admin)
# If any of these NEED user filtering/display, create a simple CustomAdmin subclass for them
admin.site.register(Category) # Example: Might need user filtering if categories are user-specific
admin.site.register(Supplier) # Example: Might need user filtering
admin.site.register(Product) # Example: Might need user filtering
admin.site.register(InventoryTransaction) # Example: Likely needs user filtering
admin.site.register(StorefrontHeroShowcase)
admin.site.register(StorefrontHeroShowcaseItem)
admin.site.register(StorefrontHeroPackage)
admin.site.register(StorefrontMessageBanner)

# --- Admin Site Customization ---
admin.site.site_header = "Smart Invoices Administration" # Updated Title
admin.site.site_title = "Smart Invoices Portal"
admin.site.index_title = "Welcome to Smart Invoices Management"
