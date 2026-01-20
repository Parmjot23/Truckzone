# accounts/views.py

from decimal import Decimal
import logging
import threading
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
try:
    from weasyprint import CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    CSS = None
from accounts.models import GroupedInvoice, GroupedEstimate, InvoiceActivity
from .invoice_activity import (
    log_invoice_activity,
    build_email_open_tracking_url,
    resolve_invoice_id_from_token,
)
from .ai_service import generate_dynamic_invoice_note
from .utils import resolve_company_logo_url, build_cc_list
from .view_workorder import generate_pm_inspection_pdf
from .pdf_utils import render_template_to_pdf_cached, render_template_to_pdf, apply_branding_defaults

PDF_STYLESHEET = CSS(string='@page { size: A4; margin: 1cm; }') if WEASYPRINT_AVAILABLE else None
logger = logging.getLogger(__name__)


def _send_grouped_invoice_email(invoice, *, request, include_workorder=False):
    profile = (
        getattr(getattr(request, 'user', None), 'profile', None)
        or getattr(invoice.user, 'profile', None)
    )

    context = _build_invoice_context(invoice, request)

    # Render the PDF for attachment
    pdf_content = _render_pdf('invoices/grouped_invoice_pdf.html', context)

    # Render the email HTML content
    context = apply_branding_defaults(context)
    email_html = render_to_string('emails/invoice_email.html', context)

    subject = f"[DO NOT REPLY] Invoice #{invoice.invoice_number} from {getattr(profile, 'company_name', '')}"
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient = invoice.bill_to_email
    customer_cc_emails = invoice.customer.get_cc_emails() if invoice.customer else []
    cc_recipients = build_cc_list(
        getattr(request.user, 'email', None),
        getattr(profile, "company_email", None),
        *customer_cc_emails,
        exclude=[recipient],
    )

    email_message = EmailMultiAlternatives(
        subject=subject,
        body="Please find attached your invoice.",
        from_email=from_email,
        to=[recipient],
        cc=cc_recipients or None,  # CC business/profile emails
    )
    email_message.attach_alternative(email_html, "text/html")
    # renamed attachment to Invoice
    email_message.attach(
        f'Invoice_{invoice.invoice_number}.pdf',
        pdf_content,
        'application/pdf'
    )
    if include_workorder and invoice.work_order:
        from .views import generate_workorder_pdf
        wo_pdf = generate_workorder_pdf(invoice.work_order, request)
        email_message.attach(
            f"WorkOrder_{invoice.work_order.id}.pdf",
            wo_pdf,
            'application/pdf'
        )
        pm_inspection = getattr(invoice.work_order, 'pm_inspection', None)
        if pm_inspection:
            pm_pdf = generate_pm_inspection_pdf(pm_inspection, request)
            email_message.attach(
                f"WorkOrder_{invoice.work_order.id}_PM.pdf",
                pm_pdf,
                'application/pdf'
            )
    email_message.send()
    log_invoice_activity(
        invoice,
        event_type=InvoiceActivity.EVENT_EMAIL_SENT,
        request=request,
    )


def _invoice_queryset_for_user(user):
    return (
        GroupedInvoice.objects
        .select_related('user__profile', 'customer', 'work_order')
        .prefetch_related('income_records', 'payments')
        .filter(user=user)
    )

# ---------------------------
# PDF Generation for Download
# ---------------------------
# ---------------------------
# PDF Generation for Download
# ---------------------------
def _build_invoice_context(invoice, request, *, profile=None):
    """Build the context needed to render a grouped invoice PDF/email."""

    # Prefer an explicitly supplied profile, otherwise fall back to the
    # authenticated user's profile, and finally the profile that owns the
    # invoice.  Customer-portal users do not have a business profile attached
    # to their account, so using the invoice owner keeps the rendering logic
    # consistent between the back office and the portal.
    profile = (
        profile
        or getattr(getattr(request, 'user', None), 'profile', None)
        or getattr(invoice.user, 'profile', None)
    )

    # Compute summaries with interest handled separately
    records = list(invoice.income_records.all())
    interest_total = sum(
        r.amount for r in records
        if r.job and str(r.job).lower().startswith('interest')
    )
    taxable_records = [
        r for r in records
        if not (r.job and str(r.job).lower().startswith('interest'))
    ]
    pre_tax_subtotal = sum(r.amount for r in taxable_records)
    if invoice.tax_exempt:
        tax = 0
        total_amount = pre_tax_subtotal + interest_total
    else:
        tax = sum(r.tax_collected for r in taxable_records)
        total_amount = pre_tax_subtotal + tax + interest_total
    subtotal = pre_tax_subtotal + interest_total

    company_logo_url = ''
    if profile:
        company_logo_url = resolve_company_logo_url(profile, request=request)

    invoice_note = (invoice.notes or '').strip()
    if invoice_note:
        note = invoice_note
    elif profile and getattr(profile, 'show_note', False):
        if getattr(profile, 'use_dynamic_note', False):
            note = generate_dynamic_invoice_note(invoice)
        else:
            note = profile.note or ''
    else:
        note = ''

    return {
        'invoice': invoice,
        'profile': profile,
        'subtotal': subtotal,
        'pre_tax_subtotal': pre_tax_subtotal,
        'interest_total': interest_total,
        'tax': tax,
        'total_amount': total_amount,
        'is_paid': invoice.payment_status == 'Paid',
        'balance_due': invoice.balance_due(),
        'total_paid_amount': invoice.total_paid(),
        'company_logo_url': company_logo_url,
        'note': note,
        'now': timezone.now(),
        'invoice_open_tracking_url': build_email_open_tracking_url(
            invoice,
            request=request,
        ),
    }


def _render_pdf(template, context):
    context_for_pdf = context.copy()
    profile = context.get('profile')
    if profile is not None:
        context_for_pdf['company_logo_url'] = resolve_company_logo_url(
            profile,
            for_pdf=True,
        )

    pdf_object = context.get('invoice') or context.get('estimate')
    if pdf_object is None:
        return render_template_to_pdf(
            template,
            context_for_pdf,
            stylesheets=[PDF_STYLESHEET],
        )

    cache_prefix = 'grouped_invoice' if 'invoice' in context else 'estimate'

    return render_template_to_pdf_cached(
        pdf_object,
        template,
        context_for_pdf,
        cache_prefix=cache_prefix,
        stylesheets=[PDF_STYLESHEET],
    )


@login_required
def generate_grouped_invoice_pdf(request, pk):
    """
    Generates the invoice PDF for download using WeasyPrint.
    """
    invoice = get_object_or_404(_invoice_queryset_for_user(request.user), pk=pk)
    context = _build_invoice_context(invoice, request)

    pdf_data = _render_pdf('invoices/grouped_invoice_pdf.html', context)

    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="Invoice_{invoice.invoice_number}.pdf"'
    )
    return response


# ---------------------------
# PDF Generation for Print (Inline View)
# ---------------------------
@login_required
def print_grouped_invoice_pdf(request, pk):
    """
    Generates the invoice PDF and returns it inline so that a print dialog can be opened.
    """
    invoice = get_object_or_404(_invoice_queryset_for_user(request.user), pk=pk)
    context = _build_invoice_context(invoice, request)

    pdf_data = _render_pdf('invoices/grouped_invoice_pdf.html', context)

    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'inline; filename="Invoice_{invoice.invoice_number}.pdf"'
    )
    return response


# ---------------------------
# Email Sending Functionality
# ---------------------------
@login_required
def send_grouped_invoice_email(request, pk):
    """
    Generates the invoice PDF and sends it via email, CC’ing the profile user.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method.'}, status=405)

    invoice = get_object_or_404(_invoice_queryset_for_user(request.user), pk=pk)
    include_workorder = request.POST.get('include_workorder') == '1'
    async_send = request.POST.get('async') == '1'

    if async_send:
        def _run_email():
            try:
                _send_grouped_invoice_email(
                    invoice,
                    request=request,
                    include_workorder=include_workorder,
                )
            except Exception:
                logger.exception("Failed to send grouped invoice email for %s", invoice.pk)

        threading.Thread(target=_run_email, daemon=True).start()
        return JsonResponse({'message': 'Invoice email queued for sending.'})

    try:
        _send_grouped_invoice_email(
            invoice,
            request=request,
            include_workorder=include_workorder,
        )
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    return JsonResponse({'message': 'Invoice email sent successfully.'})


@require_GET
@never_cache
def track_invoice_email_open(request, token):
    invoice_id = resolve_invoice_id_from_token(token)
    if invoice_id:
        invoice = GroupedInvoice.objects.filter(pk=invoice_id).first()
        if invoice:
            log_invoice_activity(
                invoice,
                event_type=InvoiceActivity.EVENT_EMAIL_OPENED,
                request=request,
            )

    pixel_bytes = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
        b"\x00\x00\x00\xff\xff\xff!\xf9\x04"
        b"\x01\x00\x00\x00\x00,\x00\x00\x00"
        b"\x00\x01\x00\x01\x00\x00\x02\x02"
        b"D\x01\x00;"
    )
    response = HttpResponse(pixel_bytes, content_type="image/gif")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def _build_estimate_context(estimate, request):
    profile = request.user.profile

    records = list(estimate.estimate_records.all())
    subtotal = sum(
        (Decimal(str(record.amount or 0)) for record in records),
        Decimal('0')
    )
    if estimate.tax_exempt:
        tax = Decimal('0')
        total_amount = subtotal
    else:
        tax = sum(
            (Decimal(str(record.tax_collected or 0)) for record in records),
            Decimal('0')
        )
        total_amount = subtotal + tax

    company_logo_url = (
        request.build_absolute_uri(profile.company_logo.url)
        if profile.company_logo else
        None
    )

    return {
        'estimate': estimate,
        'profile': profile,
        'subtotal': subtotal,
        'pre_tax_subtotal': subtotal,
        'tax': tax,
        'total_amount': total_amount,
        'company_logo_url': company_logo_url,
        'note': profile.note if profile and getattr(profile, 'show_note', False) else '',
        'now': timezone.now(),
    }


@login_required
def generate_estimate_pdf(request, pk):
    """Generate a downloadable PDF for the estimate."""
    estimate = get_object_or_404(GroupedEstimate, pk=pk, user=request.user)
    context = _build_estimate_context(estimate, request)

    pdf_data = _render_pdf('invoices/estimate_pdf.html', context)

    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="Estimate_{estimate.estimate_number}.pdf"'
    )
    return response


@login_required
def print_estimate_pdf(request, pk):
    """Render the estimate PDF inline for printing."""
    estimate = get_object_or_404(GroupedEstimate, pk=pk, user=request.user)
    context = _build_estimate_context(estimate, request)

    pdf_data = _render_pdf('invoices/estimate_pdf.html', context)

    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'inline; filename="Estimate_{estimate.estimate_number}.pdf"'
    )
    return response


@login_required
def send_estimate_email(request, pk):
    """Send the estimate PDF via email to the customer."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method.'}, status=405)

    estimate = get_object_or_404(GroupedEstimate, pk=pk, user=request.user)
    profile = request.user.profile
    context = _build_estimate_context(estimate, request)

    pdf_content = _render_pdf('invoices/estimate_pdf.html', context)
    context = apply_branding_defaults(context)
    email_html = render_to_string('emails/estimate_email.html', context)

    subject = f"[DO NOT REPLY] Estimate #{estimate.estimate_number} from {profile.company_name}"
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient = estimate.bill_to_email
    customer_cc_emails = estimate.customer.get_cc_emails() if estimate.customer else []
    cc_recipients = build_cc_list(
        request.user.email,
        getattr(profile, "company_email", None),
        *customer_cc_emails,
        exclude=[recipient],
    )

    email_message = EmailMultiAlternatives(
        subject=subject,
        body="Please find attached your estimate.",
        from_email=from_email,
        to=[recipient],
        cc=cc_recipients or None,
    )
    email_message.attach_alternative(email_html, "text/html")
    email_message.attach(
        f'Estimate_{estimate.estimate_number}.pdf',
        pdf_content,
        'application/pdf'
    )
    email_message.send()

    return JsonResponse({'message': 'Estimate email sent successfully.'})
