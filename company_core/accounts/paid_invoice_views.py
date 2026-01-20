from typing import Dict, Any, Optional
import threading

from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone

try:
    from weasyprint import CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    CSS = None
import logging
from .models import GroupedInvoice, Profile, InvoiceActivity
from .invoice_activity import log_invoice_activity, build_email_open_tracking_url
from .ai_service import generate_dynamic_invoice_note
from .utils import resolve_company_logo_url
from .view_workorder import generate_pm_inspection_pdf
from accounts.templatetags import custom_filters
from .pdf_utils import render_template_to_pdf_cached, apply_branding_defaults
from .utils import build_cc_list

PDF_CSS = CSS(string='@page{size:A4;margin:1cm;} body{font-family:Arial,sans-serif;}') if WEASYPRINT_AVAILABLE else None


def _invoice_queryset_for_user(user):
    return (
        GroupedInvoice.objects
        .select_related('user__profile', 'customer', 'work_order')
        .prefetch_related('income_records', 'payments')
        .filter(user=user)
    )
logger = logging.getLogger(__name__)

def _logo_url(profile: Profile, *, for_pdf: bool, request=None) -> str:
    """
    Returns a path that works for the given medium.

    • PDFs → local  file://…  so WeasyPrint can read it
    • E-mails → full https://…  so mail-clients can load it
    """
    return resolve_company_logo_url(
        profile,
        request=request,
        for_pdf=for_pdf,
    )

def _invoice_context(
        invoice: GroupedInvoice,
        *,
        paid: bool = True,
        request=None,
        for_email: bool = False
) -> Dict[str, Any]:
    """
    Common context generator for PDFs & emails.
    Set   for_email=True   when rendering an e-mail body;
    leave it False (default) for PDFs.
    """
    profile  = invoice.user.profile
    tax_total = sum(j.tax_collected for j in invoice.income_records.all())
    if paid:
        # prefer the explicit paid_date field if you have one;
        # fall back to the most-recent payment record.
        paid_date = getattr(invoice, "paid_date", None)
        if not paid_date and invoice.payments.exists():
            paid_date = invoice.payments.order_by("-date").first().date
    else:
        paid_date = None
    total_paid_value = invoice.total_paid()
    invoice_note = (invoice.notes or '').strip()
    if invoice_note:
        note = invoice_note
    elif getattr(profile, 'show_note', False):
        note = (
            generate_dynamic_invoice_note(invoice)
            if getattr(profile, 'use_dynamic_note', False) else
            (profile.note or '')
        )
    else:
        note = ''
    return {
        'invoice'      : invoice,
        'profile'      : profile,
        'customer'     : invoice.customer,
        'payments'     : invoice.payments.order_by('date'),
        'subtotal'     : invoice.total_amount - tax_total,
        'tax'          : tax_total,
        'total_amount' : invoice.total_amount,
        'total_paid_amount': total_paid_value,
        'total_paid'   : total_paid_value,
        'balance_due'  : invoice.balance_due(),            # will be 0.00 when paid
        'is_paid'      : paid,
        'paid_date'    : paid_date,
        'now'          : timezone.now(),                   # for footer year
        'note'         : note,
        'company_logo_url': _logo_url(
            profile,
            for_pdf = not for_email,
            request = request
        ),
        'invoice_open_tracking_url': build_email_open_tracking_url(
            invoice,
            request=request,
        ),
    }


def _render_paid_invoice_pdf(invoice: GroupedInvoice, *, request=None) -> bytes:
    context = _invoice_context(invoice, request=request)
    return render_template_to_pdf_cached(
        invoice,
        'invoices/paid_invoice_pdf.html',
        context,
        cache_prefix='paid_invoice',
        stylesheets=[PDF_CSS],
    )


@login_required
def generate_paid_invoice_pdf(request, pk: int):
    invoice = get_object_or_404(_invoice_queryset_for_user(request.user), pk=pk)
    if invoice.payment_status != 'Paid':
        return HttpResponseBadRequest('Invoice is not marked paid.')
    pdf_bytes = _render_paid_invoice_pdf(invoice, request=request)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="paid_{invoice.invoice_number}.pdf"'
    return resp


@login_required
def print_paid_invoice_pdf(request, pk: int):
    invoice = get_object_or_404(_invoice_queryset_for_user(request.user), pk=pk)
    if invoice.payment_status != 'Paid':
        return HttpResponseBadRequest('Invoice is not marked paid.')
    pdf_bytes = _render_paid_invoice_pdf(invoice, request=request)
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="paid_{invoice.invoice_number}.pdf"'
    return resp


def send_paid_invoice_email(
    invoice: GroupedInvoice,
    *,
    request=None,
    receipt_url: Optional[str] = None,
    stripe_pdf: Optional[bytes] = None,
    stripe_pdf_name: Optional[str] = None,
    include_workorder: bool = False
) -> None:
    """Render PDF, HTML body, fire the e-mail. Safe to call many times."""
    if invoice.payment_status != "Paid":
        logger.warning("Tried to e-mail unpaid invoice %s", invoice.invoice_number)
        return

    # … existing PDF‐render for your branded invoice …
    pdf_bytes = _render_paid_invoice_pdf(invoice, request=request)

    # Build e-mail context & body
    ctx_email               = _invoice_context(invoice, for_email=True, request=request)
    ctx_email["payment_receipt_url"] = receipt_url
    ctx_email["stripe_receipt_url"] = receipt_url
    ctx_email = apply_branding_defaults(ctx_email)
    html_body               = render_to_string('emails/invoice_email_paid.html', ctx_email)

    subject = f"Invoice {invoice.invoice_number} – Payment received"
    plain   = (
        f"Hi {invoice.bill_to},\n\n"
        "Thank you for your payment.\n\n"
        f"Amount paid: {custom_filters.currency(invoice.total_amount)}\n"
        f"{'View payment receipt: ' + receipt_url if receipt_url else ''}"
    )
    to      = [invoice.bill_to_email] if invoice.bill_to_email else []
    sender  = invoice.user.email
    business_email = getattr(getattr(invoice.user, "profile", None), "company_email", None)
    customer_cc_emails = invoice.customer.get_cc_emails() if invoice.customer else []
    cc_recipients = build_cc_list(
        sender,
        business_email,
        *customer_cc_emails,
        exclude=to,
    )

    email = EmailMultiAlternatives(subject, plain, sender, to, cc=cc_recipients or None)
    email.attach_alternative(html_body, "text/html")

    # attach your invoice PDF
    email.attach(f"paid_{invoice.invoice_number}.pdf", pdf_bytes, "application/pdf")

    # ← NEW: attach the Stripe‐generated PDF if provided
    if stripe_pdf and stripe_pdf_name:
        email.attach(stripe_pdf_name, stripe_pdf, "application/pdf")

    if include_workorder and invoice.work_order:
        from .views import generate_workorder_pdf
        wo_pdf = generate_workorder_pdf(invoice.work_order, request)
        email.attach(
            f"WorkOrder_{invoice.work_order.id}.pdf",
            wo_pdf,
            "application/pdf"
        )
        pm_inspection = getattr(invoice.work_order, 'pm_inspection', None)
        if pm_inspection:
            pm_pdf = generate_pm_inspection_pdf(pm_inspection, request)
            email.attach(
                f"WorkOrder_{invoice.work_order.id}_PM.pdf",
                pm_pdf,
                "application/pdf"
            )

    email.send()
    log_invoice_activity(
        invoice,
        event_type=InvoiceActivity.EVENT_EMAIL_SENT,
        request=request,
    )

@login_required
def send_paid_invoice_email_view(request, pk):
    invoice = get_object_or_404(_invoice_queryset_for_user(request.user), pk=pk)
    include_workorder = request.POST.get('include_workorder') == '1'
    async_send = request.POST.get('async') == '1'

    if async_send:
        def _run_email():
            try:
                send_paid_invoice_email(
                    invoice,
                    request=request,
                    include_workorder=include_workorder
                )
            except Exception:
                logger.exception("Failed to send paid invoice email for %s", invoice.pk)

        threading.Thread(target=_run_email, daemon=True).start()
        return JsonResponse({'message': 'Paid invoice email queued for sending.'}, status=200)

    try:
        send_paid_invoice_email(
            invoice,
            request=request,
            include_workorder=include_workorder
        )   # receipt_url defaults to None
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)
    return JsonResponse({'message': 'Paid invoice emailed.'}, status=200)
