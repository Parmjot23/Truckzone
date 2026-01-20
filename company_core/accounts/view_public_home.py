# view_public_home.py
from decimal import Decimal

from django.shortcuts import render, get_object_or_404

from .models import GroupedInvoice


def work_order(request):
    """
    Renders the Work Order feature page with static content.
    """
    return render(request, "public/work_order.html", {})

def inventory(request):
    """
    Renders the Inventory Management feature page with static content.
    """
    return render(request, "public/inventory.html", {})

def statements(request):
    """
    Renders the Customer Statements & Reporting page with static content.
    """
    return render(request, "public/statements.html", {})

def customer_management(request):
    """
    Renders the Customer Management page.
    The template now shows only static placeholder content.
    """
    return render(request, "public/customer_management.html", {})

def invoice_generation(request):
    """
    Renders the Invoice Generation page with static content.
    """
    return render(request, "public/invoice_generation.html", {})

def invoice_list(request):
    """
    Renders the Invoice List page with static sample data.
    """
    return render(request, "public/invoice_list.html", {})

def invoice_detail(request, invoice_id):
    """
    Renders the Invoice Detail page with real data from GroupedInvoice, falling
    back to placeholders only when the invoice lacks certain fields.
    """
    invoice = get_object_or_404(GroupedInvoice, pk=invoice_id)

    line_items = list(invoice.income_records.all())
    interest_total = sum(
        item.amount for item in line_items
        if item.job and str(item.job).lower().startswith('interest')
    )
    taxable_items = [
        item for item in line_items
        if not (item.job and str(item.job).lower().startswith('interest'))
    ]
    pre_tax_subtotal = sum((item.amount or Decimal('0.00')) for item in taxable_items)
    tax_total = sum((item.tax_collected or Decimal('0.00')) for item in taxable_items)
    subtotal = pre_tax_subtotal + interest_total
    total_amount = subtotal + tax_total

    profile = getattr(invoice.user, 'profile', None)

    context = {
        'invoice': invoice,
        'line_items': line_items,
        'subtotal': subtotal,
        'tax': tax_total,
        'total_amount': total_amount,
        'balance_due': invoice.balance_due(),
        'payments': invoice.payments.all(),
        'profile': profile,
    }
    return render(request, "public/invoice_detail.html", context)

def expense_tracking(request):
    """
    Renders the Expense Tracking page with static content.
    """
    return render(request, "public/expense_tracking.html", {})

def payment_processing(request):
    """
    Renders the Payment Processing page with static content.
    """
    return render(request, "public/payment_processing.html", {})
