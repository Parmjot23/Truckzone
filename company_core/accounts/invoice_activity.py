from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.core import signing
from django.http import HttpRequest
from django.urls import reverse

from .models import InvoiceActivity, GroupedInvoice


logger = logging.getLogger(__name__)
EMAIL_OPEN_SALT = "invoice-email-open"
EMAIL_OPEN_MAX_AGE_SECONDS = 365 * 24 * 60 * 60


def log_invoice_activity(
    invoice: GroupedInvoice,
    *,
    event_type: str,
    request: Optional[HttpRequest] = None,
    actor=None,
) -> None:
    if not invoice:
        return

    actor_user = actor
    if actor_user is None and request is not None:
        actor_user = getattr(request, "actual_user", None) or getattr(request, "user", None)

    if actor_user is not None and not getattr(actor_user, "is_authenticated", False):
        actor_user = None

    try:
        InvoiceActivity.objects.create(
            invoice=invoice,
            event_type=event_type,
            actor=actor_user,
        )
    except Exception:
        logger.exception("Failed to log invoice activity for invoice %s", invoice.pk)


def build_email_open_tracking_url(
    invoice: GroupedInvoice,
    *,
    request: Optional[HttpRequest] = None,
) -> str:
    token = signing.dumps({"invoice_id": invoice.pk}, salt=EMAIL_OPEN_SALT)
    path = reverse("accounts:invoice_email_open", args=[token])
    if request is not None:
        return request.build_absolute_uri(path)
    site_url = getattr(settings, "SITE_URL", None)
    if site_url:
        return site_url.rstrip("/") + path
    return path


def resolve_invoice_id_from_token(token: str) -> Optional[int]:
    try:
        payload = signing.loads(
            token,
            salt=EMAIL_OPEN_SALT,
            max_age=EMAIL_OPEN_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return None
    invoice_id = payload.get("invoice_id")
    if not isinstance(invoice_id, int):
        return None
    return invoice_id
