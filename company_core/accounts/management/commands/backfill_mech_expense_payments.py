import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import (
    MechExpense,
    MechExpenseItem,
    MechExpensePayment,
    PROVINCE_TAX_RATES,
)


class Command(BaseCommand):
    help = (
        "Backfill mechanic expense tax/amounts and create missing payments for paid expenses. "
        "When a paid expense has no payments, the payment date is set to the expense date."
    )

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, help='Limit updates to a specific user id.')
        parser.add_argument('--dry-run', action='store_true', help='Show counts without writing.')
        parser.add_argument('--skip-tax', action='store_true', help='Skip recalculating item amount/tax_paid.')
        parser.add_argument('--skip-payments', action='store_true', help='Skip creating payments for paid expenses.')
        parser.add_argument('--batch-size', type=int, default=500, help='Batch size for bulk updates.')

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        dry_run = options.get('dry_run')
        skip_tax = options.get('skip_tax')
        skip_payments = options.get('skip_payments')
        batch_size = options.get('batch_size') or 500

        if skip_tax and skip_payments:
            self.stdout.write(self.style.WARNING('Nothing to do (both tax and payments are skipped).'))
            return

        if not skip_tax:
            self._backfill_item_tax(user_id, dry_run, batch_size)

        if not skip_payments:
            self._backfill_payments(user_id, dry_run)

    def _backfill_item_tax(self, user_id, dry_run, batch_size):
        qs = MechExpenseItem.objects.select_related(
            'mech_expense',
            'mech_expense__user',
            'mech_expense__user__profile',
        ).filter(Q(amount=0) | Q(tax_paid=0))
        if user_id:
            qs = qs.filter(mech_expense__user_id=user_id)

        scanned = 0
        updated = 0
        to_update = []

        for item in qs.iterator(chunk_size=batch_size):
            scanned += 1
            expense = item.mech_expense
            qty = item.qty or 0
            price = item.price or 0
            amount = round(qty * price, 2)

            province = expense.province
            if not province:
                province = getattr(getattr(expense.user, "profile", None), "province", None)

            if province == 'CU' and expense.custom_tax_rate is not None:
                tax_rate = float(expense.custom_tax_rate)
            else:
                tax_rate = PROVINCE_TAX_RATES.get(province, 0)

            if expense.tax_included:
                tax_multiplier = 1 + tax_rate
                tax_paid = round(amount * (tax_rate / tax_multiplier), 2) if tax_multiplier else 0
            else:
                tax_paid = round(amount * tax_rate, 2)

            current_amount = round(item.amount or 0, 2)
            current_tax = round(item.tax_paid or 0, 2)
            if current_amount != amount or current_tax != tax_paid:
                item.amount = amount
                item.tax_paid = tax_paid
                to_update.append(item)

            if len(to_update) >= batch_size:
                updated += len(to_update)
                if not dry_run:
                    MechExpenseItem.objects.bulk_update(to_update, ['amount', 'tax_paid'])
                to_update = []

        if to_update:
            updated += len(to_update)
            if not dry_run:
                MechExpenseItem.objects.bulk_update(to_update, ['amount', 'tax_paid'])

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} {updated} item(s) out of {scanned} scanned."))

    def _backfill_payments(self, user_id, dry_run):
        expenses = MechExpense.objects.filter(paid=True).annotate(payment_count=Count('payments'))
        if user_id:
            expenses = expenses.filter(user_id=user_id)
        expenses = expenses.filter(payment_count=0)

        created = 0
        skipped_zero = 0
        skipped_date = 0

        for expense in expenses.iterator():
            total_amount_incl_tax, _, _ = expense.calculate_totals()
            total_amount = Decimal(str(total_amount_incl_tax or 0)).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )
            if total_amount <= 0:
                skipped_zero += 1
                continue

            if dry_run:
                created += 1
                continue

            payment = MechExpensePayment.objects.create(
                mech_expense=expense,
                amount=total_amount,
                method="Backfilled",
                notes="Backfilled payment for paid expense.",
                recorded_by=None,
            )
            created += 1

            if expense.date:
                paid_at = datetime.datetime.combine(expense.date, datetime.time.min)
                if timezone.is_aware(timezone.now()) and timezone.is_naive(paid_at):
                    paid_at = timezone.make_aware(paid_at, timezone.get_current_timezone())
                MechExpensePayment.objects.filter(pk=payment.pk).update(created_at=paid_at)
            else:
                skipped_date += 1

        action = "Would create" if dry_run else "Created"
        details = f"{action} {created} payment(s)."
        if skipped_zero:
            details += f" Skipped {skipped_zero} with zero totals."
        if skipped_date:
            details += f" Skipped date update for {skipped_date} missing expense dates."
        self.stdout.write(self.style.SUCCESS(details))
