"""Helpers for exchanging data with QuickBooks Desktop via IIF files."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings as django_settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    Customer,
    GroupedInvoice,
    IncomeRecord2,
    Product,
    QuickBooksSettings,
)
from .quickbooks_service import QuickBooksIntegrationError

logger = logging.getLogger(__name__)
BUSINESS_LABEL = (getattr(django_settings, "DEFAULT_BUSINESS_NAME", "") or "").strip() or "the portal"


class QuickBooksDesktopService:
    """Service layer for generating and parsing QuickBooks Desktop IIF payloads."""

    IIF_HEADERS = [
        [
            "!TRNS",
            "TRNSID",
            "TRNSTYPE",
            "DATE",
            "ACCNT",
            "NAME",
            "CLASS",
            "AMOUNT",
            "DOCNUM",
            "MEMO",
        ],
        [
            "!SPL",
            "SPLID",
            "TRNSTYPE",
            "DATE",
            "ACCNT",
            "NAME",
            "CLASS",
            "AMOUNT",
            "DOCNUM",
            "MEMO",
            "QTY",
            "RATE",
            "ITEM",
        ],
        ["!ENDTRNS"],
    ]

    def __init__(self, settings: QuickBooksSettings) -> None:
        if not settings or settings.integration_type != QuickBooksSettings.INTEGRATION_DESKTOP:
            raise QuickBooksIntegrationError("QuickBooks Desktop settings are required for this action.")
        if not settings.is_configured:
            raise QuickBooksIntegrationError("QuickBooks Desktop configuration is incomplete.")
        self.settings = settings

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
    def export_invoices(self, user) -> Tuple[int, int, str, bytes]:
        """Return invoices formatted as an IIF payload ready for download."""

        export_qs = GroupedInvoice.objects.filter(user=user).filter(
            models.Q(quickbooks_invoice_id__isnull=True) | models.Q(quickbooks_needs_sync=True)
        )

        output = StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\r\n")
        for header_row in self.IIF_HEADERS:
            writer.writerow(header_row)

        created_count = 0
        updated_count = 0
        export_timestamp = timezone.now()

        for invoice in export_qs.select_related("customer").prefetch_related("income_records__product"):
            with transaction.atomic():
                docnum = invoice.quickbooks_invoice_id or invoice.invoice_number or f"INV-{invoice.pk}"
                customer_name = self._resolve_customer_name(invoice)
                memo = invoice.bill_to or (invoice.customer.address if invoice.customer else "") or f"Imported from {BUSINESS_LABEL}"
                invoice_date = invoice.date.strftime("%m/%d/%Y") if invoice.date else export_timestamp.strftime("%m/%d/%Y")
                total_amount = self._format_decimal(invoice.total_amount)

                writer.writerow(
                    [
                        "TRNS",
                        invoice.pk,
                        "INVOICE",
                        invoice_date,
                        "Accounts Receivable",
                        customer_name,
                        "",
                        total_amount,
                        docnum,
                        memo,
                    ]
                )

                for line in invoice.income_records.all():
                    product_name = self._resolve_product_name(line)
                    description = line.job or product_name
                    amount = self._format_decimal((line.amount or Decimal("0")) + (line.tax_collected or Decimal("0")))
                    qty = self._format_decimal(line.qty or Decimal("0"))
                    rate = self._format_decimal(line.rate or Decimal("0"))

                    writer.writerow(
                        [
                            "SPL",
                            "",
                            "INVOICE",
                            invoice_date,
                            "Income",
                            customer_name,
                            "",
                            f"-{amount}",
                            docnum,
                            description,
                            qty,
                            rate,
                            product_name,
                        ]
                    )

                writer.writerow(["ENDTRNS"])

                was_existing = bool(invoice.quickbooks_invoice_id)
                invoice._skip_quickbooks_sync_flag = True
                invoice.quickbooks_invoice_id = docnum
                invoice.quickbooks_last_sync_at = export_timestamp
                invoice.quickbooks_needs_sync = False
                invoice.save(
                    update_fields=[
                        "quickbooks_invoice_id",
                        "quickbooks_last_sync_at",
                        "quickbooks_needs_sync",
                        "updated_at",
                    ]
                )

                if was_existing:
                    updated_count += 1
                else:
                    created_count += 1

        file_bytes = output.getvalue().encode("utf-8-sig")
        filename = f"quickbooks-desktop-export-{export_timestamp.strftime('%Y%m%d%H%M%S')}.iif"

        self.settings.desktop_last_exported_at = export_timestamp
        self.settings.desktop_last_export_filename = filename
        self.settings.mark_synced(
            f"Prepared QuickBooks Desktop export with {created_count} new and {updated_count} updated invoices."
        )
        self.settings.save(
            update_fields=[
                "desktop_last_exported_at",
                "desktop_last_export_filename",
                "updated_at",
            ]
        )

        return created_count, updated_count, filename, file_bytes

    # ------------------------------------------------------------------
    # Import helpers
    # ------------------------------------------------------------------
    def import_invoices(self, user, file_contents: str, source_name: str | None = None) -> Tuple[int, int]:
        """Parse an IIF payload exported from QuickBooks Desktop."""

        reader = csv.reader(StringIO(file_contents), delimiter="\t")
        created = 0
        updated = 0
        current_invoice: Optional[Dict[str, Optional[Any]]] = None
        current_lines: List[Dict[str, Optional[str]]] = []

        def flush_invoice() -> None:
            nonlocal created, updated, current_invoice, current_lines
            if not current_invoice:
                return
            try:
                with transaction.atomic():
                    invoice, was_created = self._persist_invoice(user, current_invoice, current_lines)
                if was_created:
                    created += 1
                else:
                    updated += 1
            except QuickBooksIntegrationError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Failed to import QuickBooks Desktop invoice")
                raise QuickBooksIntegrationError("Unable to import one of the QuickBooks invoices. See logs for details.") from exc
            finally:
                current_invoice = None
                current_lines = []

        for row in reader:
            if not row:
                continue
            tag = row[0].strip() if row[0] else ""
            if not tag or tag.startswith("!"):
                continue
            if tag == "TRNS":
                flush_invoice()
                current_invoice = self._parse_trns_row(row)
                current_lines = []
            elif tag == "SPL":
                if current_invoice:
                    current_lines.append(self._parse_spl_row(row))
            elif tag == "ENDTRNS":
                flush_invoice()

        flush_invoice()

        import_timestamp = timezone.now()
        self.settings.desktop_last_imported_at = import_timestamp
        if source_name:
            self.settings.desktop_last_import_filename = source_name
        self.settings.mark_synced(
            f"Imported {created} new and {updated} updated invoices from QuickBooks Desktop."
        )
        self.settings.save(
            update_fields=[
                "desktop_last_imported_at",
                "desktop_last_import_filename",
                "updated_at",
            ]
        )

        return created, updated

    def sync_invoices(self, user) -> Dict[str, Any]:
        """Desktop sync is a convenience wrapper around import/export."""

        created, updated, filename, payload = self.export_invoices(user)
        return {
            "exported_new": created,
            "exported_updated": updated,
            "export_filename": filename,
            "export_payload": payload,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_customer_name(self, invoice: GroupedInvoice) -> str:
        if invoice.customer and invoice.customer.name:
            return invoice.customer.name
        return invoice.bill_to or self.settings.desktop_company_name or "QuickBooks Customer"

    def _resolve_product_name(self, line: IncomeRecord2) -> str:
        if line.product and line.product.quickbooks_item_id:
            return line.product.quickbooks_item_id
        if line.product and line.product.name:
            return line.product.name
        return "QuickBooks Item"

    def _format_decimal(self, value: Decimal | None) -> str:
        if value is None:
            value = Decimal("0")
        if not isinstance(value, Decimal):
            try:
                value = Decimal(str(value))
            except (InvalidOperation, TypeError):
                value = Decimal("0")
        return f"{value.quantize(Decimal('0.01'))}"

    def _parse_trns_row(self, row: Iterable[str]) -> Dict[str, Optional[Any]]:
        cells = list(row) + [""] * (10 - len(row))
        date_value: Optional[str] = cells[3].strip() if cells[3] else None
        parsed_date: Optional[datetime.date]
        if date_value:
            try:
                parsed_date = datetime.strptime(date_value, "%m/%d/%Y").date()
            except ValueError:
                parsed_date = None
        else:
            parsed_date = None
        return {
            "docnum": cells[8].strip() or None,
            "customer": cells[5].strip() or None,
            "memo": cells[9].strip() or None,
            "amount": cells[7].strip() or None,
            "date": parsed_date,
        }

    def _parse_spl_row(self, row: Iterable[str]) -> Dict[str, Optional[str]]:
        cells = list(row) + [""] * (13 - len(row))
        return {
            "description": cells[9].strip() or None,
            "amount": cells[7].strip() or None,
            "quantity": cells[10].strip() or None,
            "rate": cells[11].strip() or None,
            "item_name": cells[12].strip() or cells[5].strip() or None,
        }

    def _parse_decimal(self, value: Optional[str]) -> Decimal:
        if not value:
            return Decimal("0")
        try:
            return Decimal(value)
        except (InvalidOperation, TypeError):
            return Decimal("0")

    def _persist_invoice(
        self,
        user,
        invoice_data: Dict[str, Optional[Any]],
        line_items: Iterable[Dict[str, Optional[str]]],
    ) -> Tuple[GroupedInvoice, bool]:
        docnum = invoice_data.get("docnum")
        invoice = None
        if docnum:
            invoice = GroupedInvoice.objects.filter(user=user, quickbooks_invoice_id=docnum).first()
            if not invoice:
                invoice = GroupedInvoice.objects.filter(user=user, invoice_number=docnum).first()

        created = False
        if not invoice:
            invoice = GroupedInvoice(user=user)
            created = True

        customer = self._get_or_create_customer(user, invoice_data.get("customer"))
        invoice._skip_quickbooks_sync_flag = True
        invoice.user = user
        invoice.customer = customer
        invoice.bill_to = customer.name if customer else invoice.bill_to
        invoice.bill_to_email = customer.email if customer else invoice.bill_to_email
        invoice.bill_to_address = customer.address if customer else invoice.bill_to_address
        invoice.date = invoice_data.get("date") or invoice.date or timezone.now().date()
        if not invoice.invoice_number:
            invoice.invoice_number = self._ensure_safe_invoice_number(
                user=user,
                invoice=invoice,
                desired=docnum,
            )
        invoice.quickbooks_invoice_id = docnum or invoice.invoice_number
        invoice.quickbooks_last_sync_at = timezone.now()
        invoice.quickbooks_needs_sync = False
        invoice.save()

        invoice.income_records.all().delete()

        for line in line_items:
            amount = self._parse_decimal(line.get("amount"))
            qty = self._parse_decimal(line.get("quantity"))
            rate = self._parse_decimal(line.get("rate"))
            if qty == Decimal("0") and amount != Decimal("0"):
                qty = Decimal("1")
                rate = amount
            elif qty != Decimal("0") and rate == Decimal("0") and amount != Decimal("0"):
                rate = (amount / qty).quantize(Decimal("0.01"))

            product = self._get_or_create_product(user, line.get("item_name"), rate)
            IncomeRecord2.objects.create(
                grouped_invoice=invoice,
                product=product,
                job=line.get("description") or product.name,
                qty=qty,
                rate=rate,
            )

        invoice.ensure_inventory_transactions()
        invoice.recalculate_total_amount()
        invoice._skip_quickbooks_sync_flag = True
        invoice.quickbooks_last_sync_at = timezone.now()
        invoice.quickbooks_needs_sync = False
        invoice.save(
            update_fields=[
                "customer",
                "bill_to",
                "bill_to_email",
                "bill_to_address",
                "date",
                "invoice_number",
                "quickbooks_invoice_id",
                "quickbooks_last_sync_at",
                "quickbooks_needs_sync",
                "updated_at",
            ]
        )

        return invoice, created

    def _get_or_create_customer(self, user, name: Optional[str]) -> Optional[Customer]:
        if not name:
            name = "QuickBooks Customer"
        customer = Customer.objects.filter(user=user, quickbooks_customer_id=name).first()
        if not customer:
            customer = Customer.objects.filter(user=user, name=name).first()
        if not customer:
            customer = Customer.objects.create(
                user=user,
                name=name,
                quickbooks_customer_id=name,
            )
        elif not customer.quickbooks_customer_id:
            customer.quickbooks_customer_id = name
            customer.save(update_fields=["quickbooks_customer_id"])
        return customer

    def _get_or_create_product(self, user, name: Optional[str], rate: Decimal) -> Product:
        item_name = name or "QuickBooks Item"
        product = Product.objects.filter(user=user, quickbooks_item_id=item_name).first()
        if not product:
            product = Product.objects.filter(user=user, name=item_name).first()
        if not product:
            base_sku = slugify(item_name) or "quickbooks-item"
            sku = base_sku
            counter = 1
            while Product.objects.filter(user=user, sku=sku).exists():
                counter += 1
                sku = f"{base_sku}-{counter}"
            price = rate if isinstance(rate, Decimal) else Decimal("0.00")
            product = Product.objects.create(
                user=user,
                name=item_name,
                sku=sku,
                description="Imported from QuickBooks Desktop",
                sale_price=price,
                cost_price=price,
                quickbooks_item_id=item_name,
            )
        elif not product.quickbooks_item_id:
            product.quickbooks_item_id = item_name
            product.save(update_fields=["quickbooks_item_id"])
        return product

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

        if len(candidate) > 20:
            return GroupedInvoice.generate_invoice_number(user)

        clash_qs = GroupedInvoice.objects.filter(invoice_number=candidate)
        if invoice.pk:
            clash_qs = clash_qs.exclude(pk=invoice.pk)
        if clash_qs.exists():
            return GroupedInvoice.generate_invoice_number(user)

        return candidate
