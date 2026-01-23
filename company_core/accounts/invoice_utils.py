import tempfile
import json
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.files.storage import default_storage
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    HTML = None
    CSS = None
from django.db.models import (
    Sum,
    Value,
    DecimalField,
    F,
    Q,
    OuterRef,
    Subquery,
    Case,
    When,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Cast
from django.utils import timezone
from django.contrib.auth.decorators import login_required
# Assuming your models.py defines GroupedInvoice, Profile, Customer, Payment, ReminderLog
from .models import (
    GroupedInvoice,
    Profile,
    Customer,
    Payment,
    ReminderLog,
    CustomerCreditItem,
    CustomerCredit,
) # Make sure Invoice model is imported if used by customer.invoices
# Assuming your templatetags are in 'accounts' app, and 'custom_filters.py' contains currency
from accounts.templatetags import custom_filters
from .utils import resolve_company_logo_url, build_cc_list, get_customer_user_ids
from .pdf_utils import apply_branding_defaults
import logging 
logger = logging.getLogger(__name__)


def _annotate_invoice_credit_totals(queryset):
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
        source_invoice=OuterRef('pk')
    ).values('source_invoice').annotate(
        total=Coalesce(
            Sum(credit_amount_expr),
            Value(Decimal('0.00')),
            output_field=amount_field,
        )
    ).values('total')
    return queryset.annotate(
        credit_total=Coalesce(
            Subquery(credit_total, output_field=amount_field),
            Value(Decimal('0.00')),
            output_field=amount_field,
        )
    )

# ---------------------------
# Standard Invoice Functions
# ---------------------------
def get_invoice_context(request, customer_id, start_date=None, end_date=None, invoice_type='pending'):
    """
    Prepares context for standard invoice statements.
    invoice_type can be 'pending', 'paid', or 'all'.
    """
    profile = get_object_or_404(Profile, user=request.user)
    customer_user_ids = get_customer_user_ids(request.user)
    customer = get_object_or_404(Customer, id=customer_id, user__in=customer_user_ids)

    invoices = customer.invoices.filter(user=request.user) # Assuming Invoice model is related as 'invoices'
    if start_date:
        invoices = invoices.filter(date__gte=start_date)
    if end_date:
        invoices = invoices.filter(date__lte=end_date)

    # Annotate computed fields (total_paid and balance_due) using payments only.
    invoices = invoices.annotate(
        total_paid=Coalesce(Sum('payments__amount'), Value(Decimal('0.00')), output_field=DecimalField())
    ).annotate(
        balance_due=ExpressionWrapper(
            F('total_amount') - F('total_paid'),
            output_field=DecimalField(),
        )
    )

    if invoice_type == 'pending':
        invoices = invoices.filter(balance_due__gt=Decimal('0.00'))
    elif invoice_type == 'paid':
        invoices = invoices.filter(balance_due__lte=Decimal('0.00'))

    if not invoices.exists():
        return None

    total_amount = invoices.aggregate(
        total=Coalesce(Sum('total_amount'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total'] or Decimal('0.00')

    total_paid = invoices.aggregate(
        total=Coalesce(Sum('payments__amount'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total'] or Decimal('0.00')

    total_balance_due = invoices.aggregate(
        total=Coalesce(Sum('balance_due'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total'] or Decimal('0.00')

    credit_rows = []
    credit_total = Decimal('0.00')
    credits_qs = CustomerCredit.objects.filter(user=request.user, customer=customer).prefetch_related(
        'items',
        'items__product',
        'items__source_invoice',
    ).order_by('-date', '-id')
    if start_date:
        credits_qs = credits_qs.filter(date__gte=start_date)
    if end_date:
        credits_qs = credits_qs.filter(date__lte=end_date)
    for credit in credits_qs:
        total_incl_tax, total_tax, total_excl_tax = credit.calculate_totals()
        total_incl_tax = Decimal(str(total_incl_tax or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_tax = Decimal(str(total_tax or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_excl_tax = Decimal(str(total_excl_tax or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        credit_total += total_incl_tax
        item_parts = []
        for item in credit.items.all():
            label = (item.description or item.part_no or '').strip()
            if not label and item.product:
                label = item.product.name or ''
            label = label.strip()
            qty = item.qty or 0
            if label:
                if qty:
                    item_parts.append(f"{qty}x {label}")
                else:
                    item_parts.append(label)
        credit_rows.append({
            'credit': credit,
            'total_incl_tax': total_incl_tax,
            'total_tax': total_tax,
            'total_excl_tax': total_excl_tax,
            'item_summary': ", ".join(item_parts),
        })

    credit_sign = Decimal('1.00') if invoice_type == 'paid' else Decimal('-1.00')
    for row in credit_rows:
        row['display_total'] = (row['total_incl_tax'] * credit_sign).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    if invoice_type == 'paid':
        total_paid += credit_total
    else:
        total_balance_due -= credit_total

    customer_email = customer.email
    start_date_actual = invoices.order_by('date').first().date
    end_date_actual = invoices.order_by('date').last().date

    # Get the company logo URL using the storage backend:
    company_logo_url = resolve_company_logo_url(profile, for_pdf=True)

    statement_labels = {
        'pending': 'Pending invoices',
        'paid': 'Paid invoices',
        'all': 'All invoices',
    }
    context = {
        'profile': profile,
        'customer': customer,
        'invoices': invoices,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_balance_due': total_balance_due,
        'credit_rows': credit_rows,
        'credit_total': credit_total,
        'credit_sign': credit_sign,
        'customer_email': customer_email,
        'company_logo_url': company_logo_url,
        'start_date': start_date_actual,
        'end_date': end_date_actual,
        'invoice_type': invoice_type,
        'statement_label': statement_labels.get(invoice_type, 'Invoice statement'),
        'generated_on': timezone.localdate(),
    }
    return apply_branding_defaults(context)


# ---------------------------
# Overdue Invoice Functions
# ---------------------------
def get_overdue_invoice_context(request, customer_id, start_date=None, end_date=None):
    """
    Prepares the context for overdue invoice statements.
    Only considers invoices with a pending balance and then filters those whose due_date is before today.
    Uses the same logo retrieval method as the standard context.
    """
    profile = get_object_or_404(Profile, user=request.user)
    customer_user_ids = get_customer_user_ids(request.user)
    customer = get_object_or_404(Customer, id=customer_id, user__in=customer_user_ids)

    # Retrieve invoices and annotate computed fields (payments only).
    invoices = customer.invoices.filter(user=request.user)
    invoices = invoices.annotate(
        total_paid=Coalesce(Sum('payments__amount'), Value(Decimal('0.00')), output_field=DecimalField())
    ).annotate(
        balance_due=ExpressionWrapper(
            F('total_amount') - F('total_paid'),
            output_field=DecimalField(),
        )
    )
    # Only include invoices with a positive balance
    invoices = invoices.filter(balance_due__gt=Decimal('0.00'))

    if start_date:
        invoices = invoices.filter(date__gte=start_date)
    if end_date:
        invoices = invoices.filter(date__lte=end_date)

    # if not invoices.exists(): # This check might be too early if no invoices match date range but overdue ones exist
    #     return None

    pending_invoices_for_balance_calc = invoices # All pending invoices within date range (if specified)
    
    total_pending_balance = pending_invoices_for_balance_calc.aggregate(
        total=Coalesce(Sum('balance_due'), Value(Decimal('0.00')), output_field=DecimalField())
    )['total'] or Decimal('0.00')


    today = timezone.now().date()
    # Filter overdue invoices (ensure due_date is present and less than today) from the pending invoices
    overdue_invoices_list = [invoice for invoice in pending_invoices_for_balance_calc if invoice.due_date and invoice.due_date < today]
    
    if not overdue_invoices_list: # If no invoices are actually overdue
        return None

    total_overdue_balance = sum(invoice.balance_due for invoice in overdue_invoices_list)

    credit_rows = []
    credit_total = Decimal('0.00')
    credits_qs = CustomerCredit.objects.filter(user=request.user, customer=customer).prefetch_related(
        'items',
        'items__product',
        'items__source_invoice',
    ).order_by('-date', '-id')
    if start_date:
        credits_qs = credits_qs.filter(date__gte=start_date)
    if end_date:
        credits_qs = credits_qs.filter(date__lte=end_date)
    for credit in credits_qs:
        total_incl_tax, total_tax, total_excl_tax = credit.calculate_totals()
        total_incl_tax = Decimal(str(total_incl_tax or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_tax = Decimal(str(total_tax or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_excl_tax = Decimal(str(total_excl_tax or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        credit_total += total_incl_tax
        item_parts = []
        for item in credit.items.all():
            label = (item.description or item.part_no or '').strip()
            if not label and item.product:
                label = item.product.name or ''
            label = label.strip()
            qty = item.qty or 0
            if label:
                if qty:
                    item_parts.append(f"{qty}x {label}")
                else:
                    item_parts.append(label)
        credit_rows.append({
            'credit': credit,
            'total_incl_tax': total_incl_tax,
            'total_tax': total_tax,
            'total_excl_tax': total_excl_tax,
            'item_summary': ", ".join(item_parts),
        })

    credit_sign = Decimal('-1.00')
    for row in credit_rows:
        row['display_total'] = (row['total_incl_tax'] * credit_sign).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    total_pending_balance -= credit_total
    total_overdue_balance -= credit_total

    # Determine actual start/end dates from the overdue invoices being processed
    start_date_actual = min(inv.date for inv in overdue_invoices_list) if overdue_invoices_list else None
    end_date_actual = max(inv.date for inv in overdue_invoices_list) if overdue_invoices_list else None


    # Get the company logo URL the same way as in the standard context:
    company_logo_url = resolve_company_logo_url(profile, for_pdf=True)

    context = {
        'profile': profile,
        'customer': customer,
        'invoices': overdue_invoices_list,  # Only overdue invoices
        'total_pending_balance': total_pending_balance, # This is total pending for the customer (possibly within date range)
        'total_overdue_balance': total_overdue_balance, # This is total of actually overdue items in the list
        'credit_rows': credit_rows,
        'credit_total': credit_total,
        'credit_sign': credit_sign,
        'customer_email': customer.email,
        'company_logo_url': company_logo_url,
        'start_date': start_date_actual,
        'end_date': end_date_actual,
        'generated_on': timezone.localdate(),
    }
    return apply_branding_defaults(context)


def send_emails(user_email, customer_email, pdf_content, customer, profile, statement_context=None):
    """
    Sends standard invoice statement email to the customer with the internal user included in the CC.
    """
    subject = f"[DO NOT REPLY] Invoice Statement for {customer.name}"
    from_email = settings.DEFAULT_FROM_EMAIL

    statement_context = statement_context or {}
    email_context = {
        'customer': customer,
        'profile': profile,
        'current_year': timezone.now().year,
        'contact_email': user_email,
        'invoice_type': statement_context.get('invoice_type') or 'pending',
        'start_date': statement_context.get('start_date'),
        'end_date': statement_context.get('end_date'),
        'total_amount': statement_context.get('total_amount') or Decimal('0.00'),
        'total_paid': statement_context.get('total_paid') or Decimal('0.00'),
        'total_balance_due': statement_context.get('total_balance_due') or Decimal('0.00'),
        'statement_label': statement_context.get('statement_label') or 'Invoice statement',
    }
    email_context = apply_branding_defaults(email_context)
    html_content = render_to_string('emails/customer_email.html', email_context)
    body = (
        "Please find attached your invoice statement.\n"
        f"If you have any questions, please contact us at {user_email}."
    )
    customer_cc_emails = customer.get_cc_emails() if customer else []
    cc_recipients = build_cc_list(
        user_email,
        getattr(profile, "company_email", None),
        *customer_cc_emails,
        exclude=[customer_email],
    )
    # Create a single email that sends to the customer and includes the internal user in CC
    email_message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_email,
        to=[customer_email],
        cc=cc_recipients or None,
    )
    email_message.attach_alternative(html_content, "text/html")
    email_message.attach('Invoice_Statement.pdf', pdf_content, 'application/pdf')
    email_message.send()


# MODIFIED FUNCTION HERE:
def send_overdue_emails(user_email, customer_email, pdf_content, customer, profile,
                        total_pending_balance, total_overdue_balance, reminder_info=None,
                        start_date=None, end_date=None): # <-- ADDED reminder_info
    """
    Sends overdue invoice statement email to the customer with the internal user included in the CC.
    Uses the overdue_customer_email.html template for the email content.
    Now accepts and uses reminder_info.
    """
    subject_prefix = f"[DO NOT REPLY] Overdue Invoice Reminder for {customer.name}"
    if reminder_info and reminder_info.get('current_sequence'):
        subject = f"{subject_prefix} (Reminder #{reminder_info['current_sequence']})"
    else:
        subject = subject_prefix
        
    from_email = settings.DEFAULT_FROM_EMAIL

    # Render the overdue customer email template
    email_context = {
        'customer': customer,
        'profile': profile,
        'current_year': timezone.now().year,
        'contact_email': user_email,
        'total_pending_balance': total_pending_balance,
        'total_overdue_balance': total_overdue_balance,
        'reminder_info': reminder_info,  # <-- PASS reminder_info TO TEMPLATE CONTEXT
        'start_date': start_date,
        'end_date': end_date,
    }
    email_context = apply_branding_defaults(email_context)
    html_content = render_to_string('emails/overdue_customer_email.html', email_context)
    
    body = (
        "Please find attached your overdue invoice statement. Your current overdue balance is " +
        custom_filters.currency(total_overdue_balance) +
        ". "
    )
    if reminder_info and reminder_info.get('current_sequence', 0) > 1 and reminder_info.get('last_sent_on'):
        last_sent_date_str = reminder_info['last_sent_on'].strftime('%Y-%m-%d')
        body += f"We last reminded you on {last_sent_date_str}. "
    
    body += "Please remit payment immediately to avoid additional fees."

    customer_cc_emails = customer.get_cc_emails() if customer else []
    cc_recipients = build_cc_list(
        user_email,
        getattr(profile, "company_email", None),
        *customer_cc_emails,
        exclude=[customer_email],
    )
    # Create a single email that sends to the customer and includes the internal user in CC
    email_message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_email,
        to=[customer_email],
        cc=cc_recipients or None,
    )
    email_message.attach_alternative(html_content, "text/html")
    email_message.attach('Overdue_Invoice_Statement.pdf', pdf_content, 'application/pdf')
    email_message.send()


# ---------------------------
# PDF Generation & Email Sending Views
# ---------------------------
@login_required
def download_invoice_pdf(request, customer_id):
    """
    Generates and returns the invoice PDF for download based on the selected date range and invoice type.
    Uses the overdue template if invoice_type is 'overdue'.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    invoice_type = request.GET.get('invoice_type', 'pending')

    if invoice_type == 'overdue':
        context = get_overdue_invoice_context(request, customer_id, start_date=start_date_str, end_date=end_date_str)
        template_name = 'app/overdue_invoice_statement.html'
    else:
        context = get_invoice_context(request, customer_id, start_date=start_date_str, end_date=end_date_str, invoice_type=invoice_type)
        template_name = 'app/invoice_statement.html'

    if not context:
        return render(request, 'app/no_invoices.html', {'message': 'No invoices found for the selected criteria.'})


    html_string = render_to_string(template_name, context)
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not available. PDF generation is disabled. Please install GTK+ libraries for Windows.")
    html = HTML(string=html_string)
    css = CSS(string='@page { size: A4; margin: 1cm; } body { font-family: Arial, sans-serif; }') if WEASYPRINT_AVAILABLE else None

    with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf') as pdf_file:
        html.write_pdf(target=pdf_file.name, stylesheets=[css])
        pdf_file.seek(0)
        response = HttpResponse(pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{invoice_type}_invoice_statement_{context["customer"].name}.pdf"'
        return response


@login_required
def print_invoice_pdf(request, customer_id):
    """
    Generates and returns the invoice PDF for inline display (printing) based on the selected date range and invoice type.
    Uses the overdue template if invoice_type is 'overdue'.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    invoice_type = request.GET.get('invoice_type', 'pending')

    if invoice_type == 'overdue':
        context = get_overdue_invoice_context(request, customer_id, start_date=start_date_str, end_date=end_date_str)
        template_name = 'app/overdue_invoice_statement.html'
    else:
        context = get_invoice_context(request, customer_id, start_date=start_date_str, end_date=end_date_str, invoice_type=invoice_type)
        template_name = 'app/invoice_statement.html'

    if not context:
        return render(request, 'app/no_invoices.html', {'message': 'No invoices found for the selected criteria.'})


    html_string = render_to_string(template_name, context)
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not available. PDF generation is disabled. Please install GTK+ libraries for Windows.")
    html = HTML(string=html_string)
    css = CSS(string='@page { size: A4; margin: 1cm; } body { font-family: Arial, sans-serif; }') if WEASYPRINT_AVAILABLE else None

    with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf') as pdf_file:
        html.write_pdf(target=pdf_file.name, stylesheets=[css])
        pdf_file.seek(0)
        response = HttpResponse(pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{invoice_type}_invoice_statement_{context["customer"].name}.pdf"'
        return response


@login_required
def send_invoice_statement(request, customer_id):
    """
    Generates the invoice PDF and sends it via email based on the selected date range and invoice type.
    Uses overdue templates and email functions if invoice_type is 'overdue'.
    This view is intended to be called by AJAX, sending JSON.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            start_date_str = data.get('start_date') # Expecting string dates
            end_date_str = data.get('end_date')
            invoice_type = data.get('invoice_type', 'pending')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data.'}, status=400)

        # The get_overdue_invoice_context and get_invoice_context expect date objects or None
        # If you pass string dates from JSON, they need to be converted or handled inside those functions
        # For simplicity, this example assumes context functions can handle string dates or they are None

        is_overdue_type = (invoice_type == 'overdue')

        if is_overdue_type:
            context_generating_function = get_overdue_invoice_context
            template_name = 'app/overdue_invoice_statement.html'
        else:
            context_generating_function = get_invoice_context
            template_name = 'app/invoice_statement.html'
        
        context_params = {'start_date': start_date_str, 'end_date': end_date_str}
        if not is_overdue_type:
            context_params['invoice_type'] = invoice_type
            
        context = context_generating_function(request, customer_id, **context_params)

        if not context:
            return JsonResponse({'error': 'No invoices found for the selected criteria.'}, status=400)

        # If this is an overdue reminder triggered specifically, we need reminder_info
        # This 'send_invoice_statement' view might not be the one that generates 'reminder_info'
        # 'trigger_overdue_reminder' is the one that does.
        # If 'invoice_type' is 'overdue' here, it's a generic overdue statement, not necessarily a sequenced reminder.
        # For this specific view, we might not have reminder_info unless we explicitly fetch it.

        html_string = render_to_string(template_name, context)
        if not WEASYPRINT_AVAILABLE:
            raise ImportError("WeasyPrint is not available. PDF generation is disabled. Please install GTK+ libraries for Windows.")
        html = HTML(string=html_string)
        css = CSS(string='@page { size: A4; margin: 1cm; } body { font-family: Arial, sans-serif; }') if WEASYPRINT_AVAILABLE else None

        with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf') as pdf_file:
            html.write_pdf(target=pdf_file.name, stylesheets=[css])
            pdf_file.seek(0)
            pdf_content = pdf_file.read()
            
            if is_overdue_type:
                # For a generic overdue statement from this view, we don't have reminder_info
                # unless we query it here based on the customer.
                # Let's assume for this specific path, reminder_info is not applicable
                # or if it is, it needs to be fetched.
                # The 'trigger_overdue_reminder' view is where 'reminder_info' is constructed.
                send_overdue_emails(
                    user_email=request.user.email,
                    customer_email=context['customer_email'],
                    pdf_content=pdf_content,
                    customer=context['customer'],
                    profile=context['profile'],
                    total_pending_balance=context['total_pending_balance'],
                    total_overdue_balance=context['total_overdue_balance'],
                    reminder_info=None, # Explicitly None, as this isn't the sequenced reminder trigger
                    start_date=context.get('start_date'),
                    end_date=context.get('end_date'),
                )
            else:
                send_emails(
                    user_email=request.user.email,
                    customer_email=context['customer_email'],
                    pdf_content=pdf_content,
                    customer=context['customer'],
                    profile=context['profile'],
                    statement_context=context,
                )
        return JsonResponse({'message': 'Email sent successfully.'})
    else:
        return JsonResponse({'error': 'Invalid request method.'}, status=405)


@login_required
def trigger_overdue_reminder(request, customer_id):
    """
    Processes overdue invoices for a customer and sends overdue reminder emails.
    Uses the dedicated overdue invoice statement template and overdue email functions.
    Now tracks reminder history and passes it to send_overdue_emails.
    """
    if request.method == 'POST':
        try:
            customer_user_ids = get_customer_user_ids(request.user)
            customer = get_object_or_404(Customer, id=customer_id, user__in=customer_user_ids)
            profile = request.user.profile # Assuming profile exists

            # Enforce: only one reminder per customer per day.
            today = timezone.localdate()
            already_sent_today = ReminderLog.objects.filter(
                customer=customer,
                sent_at__date=today,
            ).exists()
            if already_sent_today:
                return JsonResponse(
                    {
                        'error': 'Reminder already sent today.',
                        'already_sent': True,
                        'sent_on': today.isoformat(),
                    },
                    status=400,
                )

            # --- Fetch Reminder History ---
            previous_reminders = customer.reminder_logs.all() 
            previous_reminder_count = previous_reminders.count()
            last_reminder_sent_on = previous_reminders.first().sent_at if previous_reminders.exists() else None
            
            # Get context for overdue invoices (this will contain the list of overdue invoices and balances)
            # We call get_overdue_invoice_context which already filters for overdue invoices
            # No need to pass start_date/end_date for a general reminder, let it use all relevant.
            overdue_context = get_overdue_invoice_context(request, customer_id)

            if not overdue_context or not overdue_context.get('invoices'):
                return JsonResponse({'error': 'No overdue invoices found for this customer.'}, status=400)

            # Extract necessary info from overdue_context
            overdue_invoices_list = overdue_context['invoices']
            total_pending_balance = overdue_context['total_pending_balance'] # As calculated by get_overdue_invoice_context
            total_overdue_balance = overdue_context['total_overdue_balance'] # As calculated by get_overdue_invoice_context
            company_logo_url = overdue_context['company_logo_url']
            # Actual start/end dates from the overdue invoices being sent
            actual_start_date = overdue_context['start_date']
            actual_end_date = overdue_context['end_date']


            current_reminder_sequence = previous_reminder_count + 1
            reminder_info_for_templates = {
                'current_sequence': current_reminder_sequence,
                'last_sent_on': last_reminder_sent_on,
            }

            # Context for the PDF template
            pdf_render_context = {
                'profile': profile,
                'customer': customer,
                'invoices': overdue_invoices_list, # The actual list of overdue invoices
                'total_pending_balance': total_pending_balance,
                'total_overdue_balance': total_overdue_balance,
                'start_date': actual_start_date, # Use actual dates of invoices in statement
                'end_date': actual_end_date,   # Use actual dates of invoices in statement
                'customer_email': customer.email,
                'company_logo_url': company_logo_url,
                'reminder_info': reminder_info_for_templates, 
            }
            pdf_render_context = apply_branding_defaults(pdf_render_context)

            html_string = render_to_string('app/overdue_invoice_statement.html', pdf_render_context)
            css = CSS(string='@page { size: A4; margin: 1cm; } body { font-family: Arial, sans-serif; }') if WEASYPRINT_AVAILABLE else None
            with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf') as pdf_file:
                HTML(string=html_string).write_pdf(target=pdf_file.name, stylesheets=[css])
                pdf_file.seek(0)
                pdf_content = pdf_file.read()

            send_overdue_emails(
                user_email=request.user.email,
                customer_email=customer.email,
                pdf_content=pdf_content,
                customer=customer,
                profile=profile,
                total_pending_balance=total_pending_balance,
                total_overdue_balance=total_overdue_balance,
                reminder_info=reminder_info_for_templates, # Pass the constructed reminder info
                start_date=actual_start_date,
                end_date=actual_end_date,
            )

            ReminderLog.objects.create(customer=customer)

            # For dynamic update on the frontend, include the new reminder info in the response
            response_data = {
                'message': f'Overdue reminder #{current_reminder_sequence} sent successfully.',
                'new_reminder_count': current_reminder_sequence,
                'new_last_reminder_display': 'Today' # The template will show 'Today'
            }
            return JsonResponse(response_data)
            
        except Exception as e:
            logger.exception("Error in trigger_overdue_reminder")
            return JsonResponse({'error': f'An error occurred: {str(e)}'}, status=500)
    return JsonResponse({'error': 'Invalid request method.'}, status=405)
