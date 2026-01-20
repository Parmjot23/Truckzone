# accounts/management/commands/find_invoices_missing_payments.py

from django.core.management.base import BaseCommand
from accounts.models import GroupedInvoice
from django.db.models import Sum, F, Q
from decimal import Decimal, ROUND_HALF_UP

class Command(BaseCommand):
    help = 'Finds all invoices marked as paid but missing Payment records or with insufficient payments.'

    def handle(self, *args, **kwargs):
        # Define a small epsilon for floating point comparison
        epsilon = Decimal('0.01')

        # Query 1: Invoices marked as paid but have no payments
        no_payment_invoices = GroupedInvoice.objects.filter(
            paid_invoice=True,
            payments__isnull=True
        )

        # Query 2: Invoices marked as paid but have payments sum less than total_amount - epsilon
        insufficient_payment_invoices = GroupedInvoice.objects.filter(
            paid_invoice=True
        ).annotate(
            total_payments=Sum('payments__amount')
        ).filter(
            Q(total_payments__lt=F('total_amount') - epsilon) | Q(total_payments__isnull=True)
        )

        # Combine both querysets using union
        inconsistent_invoices = no_payment_invoices.union(insufficient_payment_invoices)

        # Count of inconsistent invoices
        inconsistent_count = inconsistent_invoices.count()
        self.stdout.write(f"Total Inconsistent Invoices Found: {inconsistent_count}")

        if inconsistent_count == 0:
            self.stdout.write(self.style.SUCCESS('No inconsistent invoices found.'))
            return

        self.stdout.write(self.style.WARNING('Invoices marked as paid but missing or insufficient Payment records:'))

        for invoice in inconsistent_invoices:
            # Calculate total payments
            total_payments = invoice.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            # Calculate balance due
            balance_due = invoice.total_amount - total_payments
            balance_due = balance_due.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            self.stdout.write(
                f"User: {invoice.user.username}, "
                f"Invoice Number: {invoice.invoice_number}, "
                f"Total Amount: ${invoice.total_amount}, "
                f"Total Payments: ${total_payments}, "
                f"Balance Due: ${balance_due}"
            )
