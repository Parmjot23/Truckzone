"""Utility helpers for synchronizing invoices with QuickBooks Online."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings as django_settings
from django.db import models, transaction
from django.utils import timezone

from intuitlib.client import AuthClient
from quickbooks import QuickBooks
from quickbooks.exceptions import QuickbooksException
from quickbooks.objects.customer import Customer as QuickBooksCustomer
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.item import Item as QuickBooksItem

from .models import (
    Customer,
    GroupedInvoice,
    IncomeRecord2,
    Product,
    QuickBooksSettings,
)

logger = logging.getLogger(__name__)
BUSINESS_LABEL = (getattr(django_settings, "DEFAULT_BUSINESS_NAME", "") or "").strip() or "the portal"


class QuickBooksIntegrationError(Exception):
    """Raised when an unrecoverable QuickBooks integration issue occurs."""


class QuickBooksService:
    """High level service that coordinates QuickBooks Online synchronisation."""

    def __init__(self, settings: QuickBooksSettings) -> None:
        if not settings or not settings.is_configured:
            raise QuickBooksIntegrationError("QuickBooks settings are incomplete.")
        if settings.integration_type != QuickBooksSettings.INTEGRATION_ONLINE:
            raise QuickBooksIntegrationError(
                "QuickBooks Online credentials are required for this action."
            )
        self.settings = settings
        self._client: Optional[QuickBooks] = None

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------
    def _build_auth_client(self) -> AuthClient:
        redirect_uri = self.settings.redirect_uri or "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"
        auth_client = AuthClient(
            client_id=self.settings.client_id,
            client_secret=self.settings.client_secret,
            environment=self.settings.environment,
            redirect_uri=redirect_uri,
        )
        if self.settings.access_token:
            auth_client.access_token = self.settings.access_token
        if self.settings.refresh_token:
            auth_client.refresh_token = self.settings.refresh_token
        return auth_client

    def ensure_access_token(self) -> str:
        """Ensure a valid access token exists, refreshing it when required."""

        if self.settings.has_valid_access_token():
            return self.settings.access_token  # type: ignore[return-value]

        auth_client = self._build_auth_client()
        try:
            token_response = auth_client.refresh(self.settings.refresh_token)
        except Exception as exc:  # pragma: no cover - network call
            logger.exception("Unable to refresh QuickBooks token")
            raise QuickBooksIntegrationError("Unable to refresh QuickBooks access token. Please verify your refresh token.") from exc

        access_token = getattr(auth_client, "access_token", None)
        refresh_token = getattr(auth_client, "refresh_token", None)

        expires_in: Optional[int]
        if isinstance(token_response, dict):
            expires_in = token_response.get("expires_in")
        else:
            expires_in = getattr(token_response, "expires_in", None)
        if not expires_in:
            expires_in = 3600

        self.settings.access_token = access_token
        if refresh_token:
            self.settings.refresh_token = refresh_token
        self.settings.access_token_expires_at = timezone.now() + timedelta(seconds=max(int(expires_in) - 60, 60))
        self.settings.save(update_fields=['access_token', 'refresh_token', 'access_token_expires_at', 'updated_at'])
        return self.settings.access_token  # type: ignore[return-value]

    def get_client(self) -> QuickBooks:
        """Return a QuickBooks client configured with the latest credentials."""

        if self._client:
            return self._client

        self.ensure_access_token()
        auth_client = self._build_auth_client()
        auth_client.access_token = self.settings.access_token
        auth_client.refresh_token = self.settings.refresh_token

        try:
            client = QuickBooks(
                auth_client=auth_client,
                refresh_token=self.settings.refresh_token,
                company_id=self.settings.realm_id,
            )
        except Exception as exc:  # pragma: no cover - network call
            logger.exception("Unable to initialise QuickBooks client")
            raise QuickBooksIntegrationError("Failed to initialise QuickBooks client. Please double check your credentials.") from exc

        self._client = client
        return client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def import_customers(self, user, max_results: int = 1000) -> Tuple[int, int]:
        """Import customers from QuickBooks Online into local Customer rows."""

        client = self.get_client()
        try:
            qb_customers = QuickBooksCustomer.all(qb=client, max_results=max_results)
        except Exception:  # pragma: no cover - network call / qb sdk variance
            qb_customers = QuickBooksCustomer.where("SELECT * FROM Customer", qb=client)

        created = 0
        updated = 0
        for qb_customer in qb_customers:
            qb_id = str(self._safe_get(qb_customer, "Id") or "").strip()
            if not qb_id:
                continue

            name = (
                self._safe_get(qb_customer, "DisplayName")
                or self._safe_get(qb_customer, "CompanyName")
                or self._safe_get(qb_customer, "GivenName")
                or f"QuickBooks Customer {qb_id}"
            )

            email_payload = self._safe_get(qb_customer, "PrimaryEmailAddr") or {}
            email = (
                email_payload.get("Address")
                if isinstance(email_payload, dict)
                else getattr(email_payload, "Address", None)
            )

            phone_payload = self._safe_get(qb_customer, "PrimaryPhone") or {}
            phone = (
                phone_payload.get("FreeFormNumber")
                if isinstance(phone_payload, dict)
                else getattr(phone_payload, "FreeFormNumber", None)
            )

            address_text = self._format_address(self._safe_get(qb_customer, "BillAddr"))

            customer, was_created = Customer.objects.get_or_create(
                user=user,
                quickbooks_customer_id=qb_id,
                defaults={
                    "name": str(name)[:100],
                    "email": email,
                    "phone_number": phone,
                    "address": address_text,
                },
            )

            changed_fields = []
            if name and customer.name != str(name)[:100]:
                customer.name = str(name)[:100]
                changed_fields.append("name")
            if email and customer.email != email:
                customer.email = email
                changed_fields.append("email")
            if phone and customer.phone_number != phone:
                customer.phone_number = phone
                changed_fields.append("phone_number")
            if address_text and customer.address != address_text:
                customer.address = address_text
                changed_fields.append("address")

            if was_created:
                created += 1
            elif changed_fields:
                customer.save(update_fields=changed_fields)
                updated += 1

        self.settings.mark_synced(f"Imported {created} new and {updated} updated customers from QuickBooks")
        return created, updated

    def import_items(self, user, max_results: int = 1000) -> Tuple[int, int]:
        """Import products/items from QuickBooks Online into local Product rows."""

        client = self.get_client()
        try:
            qb_items = QuickBooksItem.all(qb=client, max_results=max_results)
        except Exception:  # pragma: no cover - network call / qb sdk variance
            qb_items = QuickBooksItem.where("SELECT * FROM Item", qb=client)

        created = 0
        updated = 0
        for qb_item in qb_items:
            qb_id = str(self._safe_get(qb_item, "Id") or "").strip()
            if not qb_id:
                continue

            name = (
                self._safe_get(qb_item, "Name")
                or self._safe_get(qb_item, "FullyQualifiedName")
                or f"QuickBooks Item {qb_id}"
            )
            description = self._safe_get(qb_item, "Description") or "Imported from QuickBooks"
            sku = self._safe_get(qb_item, "Sku") or None

            unit_price = self._safe_get(qb_item, "UnitPrice")
            purchase_cost = self._safe_get(qb_item, "PurchaseCost")
            sale_price = Decimal(str(unit_price)) if unit_price is not None else None
            cost_price = Decimal(str(purchase_cost)) if purchase_cost is not None else Decimal(str(unit_price or 0))

            product = Product.objects.filter(user=user, quickbooks_item_id=qb_id).first()
            if not product:
                if sku and Product.objects.filter(user=user, sku=sku).exists():
                    sku = None
                if not sku:
                    sku = self._build_unique_sku(user, qb_id)
                Product.objects.create(
                    user=user,
                    sku=sku,
                    name=str(name)[:150],
                    description=str(description) if description is not None else "",
                    category=None,
                    supplier=None,
                    cost_price=cost_price,
                    sale_price=sale_price,
                    quantity_in_stock=0,
                    reorder_level=0,
                    quickbooks_item_id=qb_id,
                )
                created += 1
                continue

            changed_fields = []
            if name and product.name != str(name)[:150]:
                product.name = str(name)[:150]
                changed_fields.append("name")
            if description is not None and (product.description or "") != str(description):
                product.description = str(description)
                changed_fields.append("description")
            if sale_price is not None and product.sale_price != sale_price:
                product.sale_price = sale_price
                changed_fields.append("sale_price")
            if cost_price is not None and product.cost_price != cost_price:
                product.cost_price = cost_price
                changed_fields.append("cost_price")
            if sku and product.sku != sku and not Product.objects.filter(user=user, sku=sku).exclude(pk=product.pk).exists():
                product.sku = sku
                changed_fields.append("sku")

            if changed_fields:
                product.save(update_fields=changed_fields)
                updated += 1

        self.settings.mark_synced(f"Imported {created} new and {updated} updated items from QuickBooks")
        return created, updated

    def export_invoices(self, user) -> Tuple[int, int]:
        """Push invoices created in the portal to QuickBooks."""

        client = self.get_client()
        export_qs = GroupedInvoice.objects.filter(user=user).filter(
            models.Q(quickbooks_invoice_id__isnull=True) | models.Q(quickbooks_needs_sync=True)
        )

        created_count = 0
        updated_count = 0

        for invoice in export_qs.select_related('customer').prefetch_related('income_records__product'):
            with transaction.atomic():
                was_existing = bool(invoice.quickbooks_invoice_id)
                qb_invoice = self._build_quickbooks_invoice(invoice)
                try:
                    qb_invoice.save(qb=client)
                except QuickbooksException as exc:  # pragma: no cover - network call
                    logger.exception("QuickBooks rejected invoice export")
                    raise QuickBooksIntegrationError(f"QuickBooks rejected invoice export: {exc}") from exc

                invoice._skip_quickbooks_sync_flag = True
                invoice.quickbooks_invoice_id = qb_invoice.Id
                invoice.quickbooks_sync_token = qb_invoice.SyncToken
                invoice.quickbooks_last_sync_at = timezone.now()
                invoice.quickbooks_needs_sync = False
                update_fields = [
                    'quickbooks_invoice_id',
                    'quickbooks_sync_token',
                    'quickbooks_last_sync_at',
                    'quickbooks_needs_sync',
                    'updated_at',
                ]
                invoice.save(update_fields=update_fields)

                if was_existing:
                    updated_count += 1
                else:
                    created_count += 1

        message = f"Exported {created_count} new and {updated_count} updated invoices to QuickBooks"
        self.settings.mark_synced(message)
        return created_count, updated_count

    def import_invoices(self, user, since: Optional[datetime] = None) -> Tuple[int, int]:
        """Fetch invoices from QuickBooks and mirror them locally."""

        client = self.get_client()
        if since:
            formatted = self._format_datetime_for_query(since)
            query = f"SELECT * FROM Invoice WHERE Metadata.LastUpdatedTime >= '{formatted}' ORDER BY Metadata.LastUpdatedTime DESC"
        else:
            query = "SELECT * FROM Invoice ORDER BY Metadata.LastUpdatedTime DESC"

        try:
            invoices = Invoice.where(query, qb=client)
        except QuickbooksException as exc:  # pragma: no cover - network call
            logger.exception("QuickBooks invoice query failed")
            raise QuickBooksIntegrationError(f"Unable to query invoices from QuickBooks: {exc}") from exc

        created = 0
        updated = 0
        for qb_invoice in invoices:
            with transaction.atomic():
                invoice, was_created = self._sync_invoice_from_quickbooks(user, qb_invoice)
                if was_created:
                    created += 1
                else:
                    updated += 1

        message = f"Imported {created} new and {updated} updated invoices from QuickBooks"
        self.settings.mark_synced(message)
        return created, updated

    def sync_invoices(self, user) -> Dict[str, int]:
        """Perform a full two-way synchronisation."""

        exported_new, exported_existing = self.export_invoices(user)
        imported_new, imported_existing = self.import_invoices(user)
        return {
            'exported_new': exported_new,
            'exported_updated': exported_existing,
            'imported_new': imported_new,
            'imported_updated': imported_existing,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_quickbooks_invoice(self, invoice: GroupedInvoice) -> Invoice:
        """Translate a local invoice into a QuickBooks invoice object."""

        if not invoice.customer:
            raise QuickBooksIntegrationError(
                f"Invoice {invoice.invoice_number} does not have an associated customer."
            )

        customer_id = self._ensure_quickbooks_customer(invoice.customer)
        qb_invoice = Invoice()
        if invoice.quickbooks_invoice_id:
            qb_invoice.Id = invoice.quickbooks_invoice_id
            if invoice.quickbooks_sync_token:
                qb_invoice.SyncToken = invoice.quickbooks_sync_token

        qb_invoice.CustomerRef = {"value": customer_id}
        qb_invoice.DocNumber = invoice.invoice_number
        if invoice.date:
            qb_invoice.TxnDate = invoice.date.strftime("%Y-%m-%d")
        if invoice.due_date:
            qb_invoice.DueDate = invoice.due_date.strftime("%Y-%m-%d")

        if invoice.bill_to_email:
            qb_invoice.BillEmail = {"Address": invoice.bill_to_email}
        if invoice.bill_to_address:
            qb_invoice.BillAddr = self._address_from_text(invoice.bill_to_address)

        qb_invoice.Line = self._build_quickbooks_lines(invoice)
        qb_invoice.PrivateNote = f"Synced from {BUSINESS_LABEL} on {timezone.now().isoformat()}"
        qb_invoice.TotalAmt = float(invoice.total_amount)
        return qb_invoice

    def _build_quickbooks_lines(self, invoice: GroupedInvoice) -> List[Dict[str, Any]]:
        lines: List[Dict[str, Any]] = []
        for line in invoice.income_records.all():
            if line.product and not line.product.quickbooks_item_id:
                raise QuickBooksIntegrationError(
                    f"Product '{line.product.name}' is missing a QuickBooks item mapping."
                )

            detail: Dict[str, Any] = {
                "Qty": float(line.qty or Decimal('0')),
                "UnitPrice": float(line.rate or Decimal('0')),
            }
            if line.product and line.product.quickbooks_item_id:
                detail["ItemRef"] = {"value": line.product.quickbooks_item_id, "name": line.product.name}

            lines.append(
                {
                    "Amount": float(line.amount or Decimal('0')),
                    "DetailType": "SalesItemLineDetail",
                    "Description": line.job or (line.product.name if line.product else "Service"),
                    "SalesItemLineDetail": detail,
                }
            )
        return lines

    def _ensure_quickbooks_customer(self, customer: Customer) -> str:
        if customer.quickbooks_customer_id:
            return customer.quickbooks_customer_id

        client = self.get_client()
        qb_customer = QuickBooksCustomer()
        qb_customer.DisplayName = customer.name or "Customer"
        if customer.email:
            qb_customer.PrimaryEmailAddr = {"Address": customer.email}
        if customer.phone_number:
            qb_customer.PrimaryPhone = {"FreeFormNumber": customer.phone_number}
        if customer.address:
            qb_customer.BillAddr = self._address_from_text(customer.address)

        try:
            qb_customer.save(qb=client)
        except QuickbooksException as exc:  # pragma: no cover - network call
            logger.exception("Unable to create QuickBooks customer")
            raise QuickBooksIntegrationError(f"Unable to create customer in QuickBooks: {exc}") from exc

        customer.quickbooks_customer_id = qb_customer.Id
        customer.save(update_fields=['quickbooks_customer_id'])
        return customer.quickbooks_customer_id

    def _sync_invoice_from_quickbooks(self, user, qb_invoice: Invoice) -> Tuple[GroupedInvoice, bool]:
        qb_invoice_id = str(self._safe_get(qb_invoice, 'Id'))
        invoice = GroupedInvoice.objects.filter(user=user, quickbooks_invoice_id=qb_invoice_id).first()
        created = False

        if not invoice:
            invoice = GroupedInvoice(user=user)
            created = True

        invoice._skip_quickbooks_sync_flag = True
        invoice.quickbooks_invoice_id = qb_invoice_id
        invoice.quickbooks_sync_token = str(self._safe_get(qb_invoice, 'SyncToken') or '0')
        invoice.quickbooks_last_sync_at = timezone.now()
        invoice.quickbooks_needs_sync = False

        customer_ref = self._safe_get(qb_invoice, 'CustomerRef') or {}
        customer = self._get_or_create_local_customer(user, customer_ref)
        invoice.customer = customer
        invoice.bill_to = customer.name if customer else invoice.bill_to

        bill_email = self._safe_get(qb_invoice, 'BillEmail') or {}
        invoice.bill_to_email = bill_email.get('Address') if isinstance(bill_email, dict) else getattr(bill_email, 'Address', None)

        bill_addr = self._safe_get(qb_invoice, 'BillAddr')
        invoice.bill_to_address = self._format_address(bill_addr)
        desired_invoice_number = self._safe_get(qb_invoice, 'DocNumber') or invoice.invoice_number
        invoice.invoice_number = self._ensure_safe_invoice_number(
            user=user,
            invoice=invoice,
            desired=desired_invoice_number,
        )

        txn_date = self._safe_get(qb_invoice, 'TxnDate')
        if txn_date:
            invoice.date = self._parse_quickbooks_date(txn_date)

        total_amount = self._safe_get(qb_invoice, 'TotalAmt')
        if total_amount is not None:
            invoice.total_amount = Decimal(str(total_amount))

        tax_detail = self._safe_get(qb_invoice, 'TxnTaxDetail') or {}
        total_tax = self._safe_get(tax_detail, 'TotalTax')
        if total_tax is not None:
            invoice.tax_exempt = Decimal(str(total_tax)) == Decimal('0')

        invoice.save()

        # Replace line items with the QuickBooks source of truth
        invoice.income_records.all().delete()
        for qb_line in self._safe_iter(self._safe_get(qb_invoice, 'Line')):
            detail_type = self._safe_get(qb_line, 'DetailType')
            if detail_type != 'SalesItemLineDetail':
                continue

            line_detail = self._safe_get(qb_line, 'SalesItemLineDetail') or {}
            qty = Decimal(str(self._safe_get(line_detail, 'Qty') or 0))
            rate = Decimal(str(self._safe_get(line_detail, 'UnitPrice') or 0))
            amount = Decimal(str(self._safe_get(qb_line, 'Amount') or qty * rate))
            description = self._safe_get(qb_line, 'Description')
            item_ref = self._safe_get(line_detail, 'ItemRef') or {}
            qb_item_id = str(self._safe_get(item_ref, 'value') or self._safe_get(item_ref, 'Value') or '')

            product = None
            if qb_item_id:
                product = Product.objects.filter(user=user, quickbooks_item_id=qb_item_id).first()
                if not product:
                    product_name = self._safe_get(item_ref, 'name') or description or f"QuickBooks Item {qb_item_id}"
                    sku = self._build_unique_sku(user, qb_item_id)
                    product = Product.objects.create(
                        user=user,
                        sku=sku,
                        name=product_name[:150],
                        description=description or "Imported from QuickBooks",
                        category=None,
                        supplier=None,
                        cost_price=Decimal(str(self._safe_get(line_detail, 'UnitPrice') or 0)),
                        sale_price=Decimal(str(self._safe_get(line_detail, 'UnitPrice') or 0)),
                        quantity_in_stock=0,
                        reorder_level=0,
                        quickbooks_item_id=qb_item_id,
                    )

            IncomeRecord2.objects.create(
                grouped_invoice=invoice,
                product=product,
                job=description or (product.name if product else "QuickBooks Line"),
                qty=qty,
                rate=rate,
                amount=amount,
                tax_collected=Decimal(str(self._safe_get(qb_line, 'TaxAmount') or 0)),
                quickbooks_line_id=str(self._safe_get(qb_line, 'Id') or ''),
            )

        invoice.ensure_inventory_transactions()
        return invoice, created

    # Helper utilities -------------------------------------------------
    @staticmethod
    def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    @staticmethod
    def _safe_iter(value: Any) -> Iterable[Any]:
        if not value:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _parse_quickbooks_date(value: Any) -> datetime.date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace('Z', '')).date()
        return value

    @staticmethod
    def _format_address(address: Any) -> Optional[str]:
        if not address:
            return None
        parts: List[str] = []
        for key in [
            'Line1', 'Line2', 'Line3', 'Line4', 'City', 'CountrySubDivisionCode', 'PostalCode', 'Country',
        ]:
            part = QuickBooksService._safe_get(address, key)
            if part:
                parts.append(str(part))
        return "\n".join(parts) if parts else None

    @staticmethod
    def _address_from_text(value: str) -> Dict[str, str]:
        lines = [line.strip() for line in (value or '').splitlines() if line.strip()]
        payload: Dict[str, str] = {}
        for index, line in enumerate(lines[:4], start=1):
            payload[f'Line{index}'] = line
        if len(lines) >= 5:
            payload['City'] = lines[4]
        return payload

    @staticmethod
    def _format_datetime_for_query(dt: datetime) -> str:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")

    @staticmethod
    def _build_unique_sku(user, quickbooks_item_id: str) -> str:
        base = f"QB-{quickbooks_item_id}-{user.id}"
        candidate = base
        counter = 1
        while Product.objects.filter(sku=candidate).exists():
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate

    @staticmethod
    def _ensure_safe_invoice_number(*, user, invoice: GroupedInvoice, desired: Any) -> str:
        """
        Ensure the invoice_number will not violate the global unique constraint.

        GroupedInvoice.invoice_number is globally unique, so imported DocNumbers can collide
        with existing invoices from other users. When that happens, we fall back to the
        per-user generated invoice number.
        """

        candidate = str(desired).strip() if desired else ""
        if not candidate:
            return GroupedInvoice.generate_invoice_number(user)

        # Enforce max length (model field is max_length=20).
        if len(candidate) > 20:
            return GroupedInvoice.generate_invoice_number(user)

        clash_qs = GroupedInvoice.objects.filter(invoice_number=candidate)
        if invoice.pk:
            clash_qs = clash_qs.exclude(pk=invoice.pk)
        if clash_qs.exists():
            return GroupedInvoice.generate_invoice_number(user)

        return candidate

    def _get_or_create_local_customer(self, user, customer_ref: Any) -> Optional[Customer]:
        qb_customer_id = str(self._safe_get(customer_ref, 'value') or self._safe_get(customer_ref, 'Value') or '')
        display_name = self._safe_get(customer_ref, 'name')
        if not qb_customer_id:
            return None
        customer, _ = Customer.objects.get_or_create(
            user=user,
            quickbooks_customer_id=qb_customer_id,
            defaults={
                'name': display_name or f"QuickBooks Customer {qb_customer_id}",
            },
        )
        if display_name and customer.name != display_name:
            customer.name = display_name
            customer.save(update_fields=['name'])
        return customer
