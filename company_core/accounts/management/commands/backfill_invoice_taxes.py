from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import (
    GroupedInvoice,
    IncomeRecord2,
    JobHistory,
    calculate_tax_total,
    ensure_decimal,
)


class Command(BaseCommand):
    help = (
        "Recalculate line-item taxes and invoice totals for specific invoice numbers "
        "using component-based rounding (QuickBooks-style)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "invoice_numbers",
            nargs="+",
            help="Invoice number(s) to backfill (space separated).",
        )
        parser.add_argument(
            "--user",
            dest="user",
            help="Optional username or user id to scope invoice lookup.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing updates.",
        )

    def handle(self, *args, **options):
        invoice_numbers = [num.strip() for num in options["invoice_numbers"] if num.strip()]
        if not invoice_numbers:
            raise CommandError("Provide at least one invoice number.")

        user_filter = {}
        user_value = options.get("user")
        if user_value:
            if str(user_value).isdigit():
                user_filter["user_id"] = int(user_value)
            else:
                user_filter["user__username__iexact"] = user_value

        dry_run = options["dry_run"]
        for invoice_number in invoice_numbers:
            qs = GroupedInvoice.objects.filter(invoice_number=invoice_number, **user_filter).select_related(
                "user",
                "user__profile",
            )
            if not qs.exists():
                self.stdout.write(
                    self.style.WARNING(f"Invoice {invoice_number}: not found (or filtered out).")
                )
                continue

            if qs.count() > 1:
                self.stdout.write(
                    self.style.WARNING(
                        f"Invoice {invoice_number}: multiple matches found; processing all."
                    )
                )

            for invoice in qs:
                line_items = list(
                    IncomeRecord2.objects.filter(grouped_invoice=invoice).order_by("id")
                )
                if not line_items:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Invoice {invoice.invoice_number} (user {invoice.user_id}): no line items."
                        )
                    )
                    continue

                old_subtotal = sum(
                    (ensure_decimal(item.amount) for item in line_items),
                    Decimal("0.00"),
                )
                old_tax = sum(
                    (ensure_decimal(item.tax_collected) for item in line_items),
                    Decimal("0.00"),
                )
                old_total = (old_subtotal + old_tax).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

                new_subtotal = Decimal("0.00")
                new_tax = Decimal("0.00")
                changed_lines = 0

                province = getattr(getattr(invoice.user, "profile", None), "province", None)
                tax_exempt = bool(getattr(invoice, "tax_exempt", False))

                def update_line(item, amount, tax_amount):
                    IncomeRecord2.objects.filter(pk=item.pk).update(
                        amount=amount,
                        tax_collected=tax_amount,
                    )
                    JobHistory.objects.filter(source_income_record=item).update(
                        service_cost=amount,
                        tax_amount=tax_amount,
                        total_job_cost=(amount + tax_amount).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        ),
                    )

                def calculate_line_tax(item, amount):
                    if tax_exempt:
                        return Decimal("0.00")
                    job_value = (item.job or "").strip().lower()
                    if job_value.startswith("interest"):
                        return Decimal("0.00")
                    return calculate_tax_total(amount, province)

                if dry_run:
                    for item in line_items:
                        qty = ensure_decimal(item.qty)
                        rate = ensure_decimal(item.rate)
                        amount = (qty * rate).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        tax_amount = calculate_line_tax(item, amount)
                        if amount != ensure_decimal(item.amount) or tax_amount != ensure_decimal(
                            item.tax_collected
                        ):
                            changed_lines += 1
                        new_subtotal += amount
                        new_tax += tax_amount
                else:
                    with transaction.atomic():
                        for item in line_items:
                            qty = ensure_decimal(item.qty)
                            rate = ensure_decimal(item.rate)
                            amount = (qty * rate).quantize(
                                Decimal("0.01"), rounding=ROUND_HALF_UP
                            )
                            tax_amount = calculate_line_tax(item, amount)
                            if amount != ensure_decimal(item.amount) or tax_amount != ensure_decimal(
                                item.tax_collected
                            ):
                                changed_lines += 1
                                update_line(item, amount, tax_amount)
                            new_subtotal += amount
                            new_tax += tax_amount

                        new_total = (new_subtotal + new_tax).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        if changed_lines or new_total != ensure_decimal(invoice.total_amount):
                            invoice.recalculate_total_amount()

                new_total = (new_subtotal + new_tax).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                status = "DRY RUN" if dry_run else "UPDATED"
                self.stdout.write(
                    f"{status} Invoice {invoice.invoice_number} (user {invoice.user_id}): "
                    f"lines={len(line_items)}, changed={changed_lines}, "
                    f"subtotal {old_subtotal:.2f}->{new_subtotal:.2f}, "
                    f"tax {old_tax:.2f}->{new_tax:.2f}, "
                    f"total {old_total:.2f}->{new_total:.2f}"
                )
