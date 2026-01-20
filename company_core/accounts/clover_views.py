import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .clover_service import (
    CloverApiError,
    CloverClient,
    build_oauth_authorize_url,
    exchange_code_for_token,
    verify_webhook_signature,
)
from .models import CloverConnection, GroupedInvoice, Payment, PaidInvoice
from .paid_invoice_views import send_paid_invoice_email

logger = logging.getLogger(__name__)


@login_required
def clover_connect(request):
    if not getattr(settings, "CLOVER_CLIENT_ID", "") or not getattr(settings, "CLOVER_REDIRECT_URI", ""):
        messages.error(request, "Clover settings are missing. Check CLOVER_CLIENT_ID and CLOVER_REDIRECT_URI.")
        return redirect("accounts:account_settings")
    state = uuid.uuid4().hex
    request.session["clover_oauth_state"] = state
    return redirect(build_oauth_authorize_url(state=state))


@login_required
def clover_callback(request):
    error = request.GET.get("error")
    if error:
        messages.error(request, f"Clover connection failed: {error}")
        return redirect("accounts:account_settings")

    state = request.GET.get("state")
    expected = request.session.pop("clover_oauth_state", None)
    if not expected or state != expected:
        messages.error(request, "Clover connection failed: invalid state.")
        return redirect("accounts:account_settings")

    code = request.GET.get("code")
    if not code:
        messages.error(request, "Clover connection failed: missing authorization code.")
        return redirect("accounts:account_settings")

    try:
        token_data = exchange_code_for_token(code)
    except CloverApiError as exc:
        messages.error(request, f"Clover connection failed: {exc}")
        return redirect("accounts:account_settings")

    merchant_id = token_data.get("merchant_id") or token_data.get("merchantId")
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    token_type = token_data.get("token_type", "")
    expires_in = token_data.get("expires_in")

    if not merchant_id or not access_token:
        messages.error(request, "Clover connection failed: missing merchant credentials.")
        return redirect("accounts:account_settings")

    expires_at = None
    if expires_in:
        try:
            expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    connection, _ = CloverConnection.objects.update_or_create(
        user=request.user,
        defaults={
            "merchant_id": merchant_id,
            "access_token": access_token,
            "token_type": token_type,
            "token_expires_at": expires_at,
            "env": getattr(settings, "CLOVER_ENVIRONMENT", "sandbox"),
        },
    )
    connection.access_token_plain = access_token
    if refresh_token:
        connection.refresh_token_plain = refresh_token
    connection.save()

    messages.success(request, "Clover connected successfully.")
    return redirect("accounts:account_settings")


@login_required
def clover_disconnect(request):
    CloverConnection.objects.filter(user=request.user).delete()
    messages.success(request, "Clover disconnected.")
    return redirect("accounts:account_settings")


def _extract_order_id(payload: dict) -> str:
    for key in ("orderId", "order_id"):
        if payload.get(key):
            return payload[key]
    order = payload.get("order") or {}
    return order.get("id") or ""


def _extract_payment_id(payload: dict) -> str:
    for key in ("paymentId", "payment_id"):
        if payload.get(key):
            return payload[key]
    payment = payload.get("payment") or {}
    return payment.get("id") or ""


def _extract_amount_cents(payload: dict) -> int:
    payment = payload.get("payment") or payload.get("data") or {}
    for key in ("amount", "amount_cents", "amountCents"):
        if payment.get(key) is not None:
            try:
                return int(payment[key])
            except (TypeError, ValueError):
                return 0
    return 0


def _extract_receipt_url(payload: dict) -> str:
    payment = payload.get("payment") or payload.get("data") or {}
    for key in ("receiptUrl", "receipt_url", "receipt_url"):
        if payment.get(key):
            return payment[key]
    return ""


@csrf_exempt
def clover_webhook(request):
    if request.method == "GET":
        verification_code = (
            request.GET.get("verificationCode")
            or request.GET.get("verification_code")
            or request.GET.get("challenge")
        )
        if verification_code:
            return HttpResponse(verification_code)
        return JsonResponse({"status": "ok"})

    payload = request.body or b"{}"
    try:
        event = json.loads(payload.decode("utf-8"))
    except ValueError:
        return JsonResponse({"status": "invalid payload"}, status=400)

    verification_code = (
        event.get("verificationCode")
        or event.get("verification_code")
        or event.get("challenge")
    )
    if verification_code:
        return HttpResponse(verification_code)

    secret = getattr(settings, "CLOVER_WEBHOOK_SECRET", "")
    signature = (
        request.META.get("HTTP_X_CLOVER_SIGNATURE")
        or request.META.get("HTTP_CLOVER_SIGNATURE")
        or ""
    )
    if secret and not verify_webhook_signature(payload, signature, secret):
        logger.warning("Clover webhook signature mismatch.")
        return JsonResponse({"status": "invalid signature"}, status=400)

    merchant_id = (
        event.get("merchantId")
        or event.get("merchant_id")
        or (event.get("merchant") or {}).get("id")
    )
    if not merchant_id:
        return JsonResponse({"status": "missing merchant"}, status=400)

    connection = CloverConnection.objects.filter(merchant_id=merchant_id).first()
    if not connection:
        return JsonResponse({"status": "unknown merchant"}, status=404)

    order_id = _extract_order_id(event)
    payment_id = _extract_payment_id(event)

    client = CloverClient(connection)

    if not order_id and payment_id:
        try:
            payment = client.get_payment(payment_id)
            order_id = (payment.get("order") or {}).get("id") or order_id
        except CloverApiError:
            order_id = order_id or ""

    if not order_id:
        return JsonResponse({"status": "ignored"}, status=200)

    invoice = GroupedInvoice.objects.filter(clover_order_id=order_id).first()
    if not invoice:
        try:
            order = client.get_order(order_id)
            note = (order.get("note") or "").strip()
            if note.startswith("invoice_id:"):
                inv_id = note.split("invoice_id:", 1)[-1].strip()
                invoice = GroupedInvoice.objects.filter(pk=inv_id).first()
                if invoice and not invoice.clover_order_id:
                    invoice.clover_order_id = order_id
                    invoice.save(update_fields=["clover_order_id"])
        except CloverApiError:
            invoice = None

    if not invoice:
        return JsonResponse({"status": "invoice not found"}, status=404)

    amount_cents = _extract_amount_cents(event)
    if amount_cents <= 0:
        try:
            payments = client.list_order_payments(order_id)
            elements = payments.get("elements") if isinstance(payments, dict) else None
            if elements:
                amount_cents = int(elements[0].get("amount") or 0)
                if not payment_id:
                    payment_id = elements[0].get("id") or payment_id
        except CloverApiError:
            amount_cents = 0

    if amount_cents <= 0:
        amount_cents = int(invoice.balance_due() * 100)

    payment_note = f"Clover payment {payment_id or order_id}"
    if Payment.objects.filter(notes__icontains=payment_note).exists():
        return JsonResponse({"status": "duplicate"}, status=200)

    amount = (Decimal(amount_cents) / Decimal("100")).quantize(Decimal("0.01"))
    with transaction.atomic():
        Payment.objects.create(
            invoice=invoice,
            amount=amount,
            method="Clover",
            notes=payment_note,
        )
        invoice.update_date_fully_paid()
        if invoice.balance_due() <= Decimal("0.01"):
            PaidInvoice.objects.get_or_create(grouped_invoice=invoice)

    receipt_url = _extract_receipt_url(event)
    try:
        send_paid_invoice_email(invoice, request=None, receipt_url=receipt_url)
    except Exception:
        logger.exception("Failed to send paid invoice email for Clover payment %s", invoice.pk)

    return JsonResponse({"status": "processed"}, status=200)
