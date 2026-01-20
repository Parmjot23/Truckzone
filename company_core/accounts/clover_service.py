import hashlib
import hmac
import logging
from urllib.parse import urlencode

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class CloverApiError(Exception):
    pass


def _clover_env():
    env = getattr(settings, "CLOVER_ENVIRONMENT", "sandbox") or "sandbox"
    env = env.strip().lower()
    if env not in {"sandbox", "production"}:
        env = "sandbox"
    return env


def _oauth_base_url():
    override = getattr(settings, "CLOVER_OAUTH_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    return "https://www.clover.com" if _clover_env() == "production" else "https://sandbox.dev.clover.com"


def _api_base_url():
    override = getattr(settings, "CLOVER_API_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    return "https://api.clover.com" if _clover_env() == "production" else "https://sandbox.dev.clover.com"


def _ecommerce_base_url():
    override = getattr(settings, "CLOVER_ECOMMERCE_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    return _api_base_url()


def _currency():
    return (getattr(settings, "CLOVER_CURRENCY", "CAD") or "CAD").upper()


def build_oauth_authorize_url(*, state: str) -> str:
    params = {
        "client_id": getattr(settings, "CLOVER_CLIENT_ID", ""),
        "redirect_uri": getattr(settings, "CLOVER_REDIRECT_URI", ""),
        "state": state,
    }
    return f"{_oauth_base_url()}/oauth/authorize?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    payload = {
        "client_id": getattr(settings, "CLOVER_CLIENT_ID", ""),
        "client_secret": getattr(settings, "CLOVER_CLIENT_SECRET", ""),
        "code": code,
        "grant_type": "authorization_code",
    }
    resp = requests.post(
        f"{_oauth_base_url()}/oauth/token",
        data=payload,
        timeout=20,
    )
    if not resp.ok:
        raise CloverApiError(f"Clover token exchange failed: {resp.status_code} {resp.text}")
    return resp.json()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class CloverClient:
    def __init__(self, connection):
        self.connection = connection
        self.api_base_url = _api_base_url()
        self.ecommerce_base_url = _ecommerce_base_url()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {connection.access_token_plain}",
                "Content-Type": "application/json",
            }
        )

    @property
    def merchant_id(self) -> str:
        return self.connection.merchant_id

    def _request(self, method: str, path: str, *, json=None, params=None, base="platform"):
        base_url = self.api_base_url if base == "platform" else self.ecommerce_base_url
        url = f"{base_url}{path}"
        resp = self.session.request(method, url, json=json, params=params, timeout=20)
        if not resp.ok:
            raise CloverApiError(f"Clover API error {resp.status_code}: {resp.text}")
        if not resp.content:
            return {}
        return resp.json()

    def create_order_for_invoice(self, invoice):
        payload = {
            "title": f"Invoice {invoice.invoice_number or invoice.pk}",
            "note": f"invoice_id:{invoice.pk}",
        }
        order = self._request(
            "POST",
            f"/v3/merchants/{self.merchant_id}/orders",
            json=payload,
        )
        order_id = order.get("id")
        if not order_id:
            return None
        line_payload = {
            "name": f"Invoice {invoice.invoice_number or invoice.pk}",
            "price": int(invoice.total_amount * 100),
            "quantity": 1,
        }
        self._request(
            "POST",
            f"/v3/merchants/{self.merchant_id}/orders/{order_id}/line_items",
            json=line_payload,
        )
        return order_id

    def create_payment_link_for_invoice(self, invoice, *, order_id: str):
        checkout_path = getattr(settings, "CLOVER_CHECKOUT_PATH", "/v1/checkout")
        if not checkout_path.startswith("/"):
            checkout_path = f"/{checkout_path}"
        success_url = getattr(settings, "CLOVER_SUCCESS_URL", "").strip()
        cancel_url = getattr(settings, "CLOVER_CANCEL_URL", "").strip()
        site_url = getattr(settings, "SITE_URL", "").rstrip("/")
        if not success_url and site_url:
            success_url = f"{site_url}/payment-successful/?invoice_number={invoice.invoice_number}"
        if not cancel_url and site_url:
            cancel_url = f"{site_url}/cancel/?invoice_number={invoice.invoice_number}"

        payload = {
            "merchantId": self.merchant_id,
            "orderId": order_id,
            "amount": int(invoice.total_amount * 100),
            "currency": _currency(),
            "customer": {"email": invoice.bill_to_email} if invoice.bill_to_email else None,
            "metadata": {
                "invoice_id": str(invoice.pk),
                "invoice_number": invoice.invoice_number or "",
            },
            "successUrl": success_url,
            "cancelUrl": cancel_url,
        }
        if payload["customer"] is None:
            payload.pop("customer")
        return self._request("POST", checkout_path, json=payload, base="ecommerce")

    def list_order_payments(self, order_id: str):
        return self._request(
            "GET",
            f"/v3/merchants/{self.merchant_id}/orders/{order_id}/payments",
        )

    def get_payment(self, payment_id: str):
        return self._request(
            "GET",
            f"/v3/merchants/{self.merchant_id}/payments/{payment_id}",
        )

    def get_order(self, order_id: str):
        return self._request(
            "GET",
            f"/v3/merchants/{self.merchant_id}/orders/{order_id}",
        )
