# accounts/management/commands/migrate_paidinvoice_dates.py

from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import GroupedInvoice, PaidInvoice, Payment, IncomeRecord2  

class Command(BaseCommand):
    help = 'Migrate date_paid from PaidInvoice to Payment.date and link IncomeRecord2 to Payment'

    def handle(self, *args, **options):
        self.stdout.write("Starting migration of date_paid to Payment.date and linking IncomeRecord2 to Payment...")

        with transaction.atomic():
            grouped_invoices = GroupedInvoice.objects.select_related('paid_invoice').all()
            total = grouped_invoices.count()
            migrated = 0

            for idx, grouped_invoice in enumerate(grouped_invoices, start=1):
                paid_invoice = getattr(grouped_invoice, 'paid_invoice', None)
                if not paid_invoice:
                    self.stdout.write(self.style.WARNING(f"[{idx}/{total}] No PaidInvoice for GroupedInvoice {grouped_invoice.invoice_number}. Skipping."))
                    continue

                payments = grouped_invoice.payments.all()
                if not payments.exists():
                    self.stdout.write(self.style.WARNING(f"[{idx}/{total}] No Payments found for GroupedInvoice {grouped_invoice.invoice_number}. Skipping."))
                    continue

                # Assuming one Payment per GroupedInvoice
                payment = payments.first()

                # Update Payment.date with PaidInvoice.date_paid
                new_date = paid_invoice.date_paid.date()  # Assuming date_paid is DateTimeField
                if payment.date != new_date:
                    old_date = payment.date
                    payment.date = new_date
                    payment.save(update_fields=['date'])
                    self.stdout.write(self.style.SUCCESS(
                        f"[{idx}/{total}] Updated Payment ID {payment.id} from date {old_date} to {new_date}."
                    ))
                    migrated += 1
                else:
                    self.stdout.write(self.style.NOTICE(
                        f"[{idx}/{total}] Payment ID {payment.id} already has the correct date {payment.date}. Skipping."
                    ))

                # Link IncomeRecord2 to Payment
                income_records = IncomeRecord2.objects.filter(grouped_invoice=grouped_invoice, payment__isnull=True)
                for record in income_records:
                    record.payment = payment
                    record.save(update_fields=['payment'])
                    self.stdout.write(self.style.SUCCESS(
                        f"  Linked IncomeRecord2 ID {record.id} to Payment ID {payment.id}."
                    ))
                    migrated += 1

            self.stdout.write(self.style.SUCCESS(
                f"Migration completed. {migrated} records updated out of {total} GroupedInvoices."
            ))
