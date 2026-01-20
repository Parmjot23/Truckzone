from django.core.management.base import BaseCommand
from accounts.models import GroupedInvoice, Payment, PendingInvoice, PaidInvoice, IncomeRecord2
from decimal import Decimal
from datetime import date

class Command(BaseCommand):
    help = 'Transfers invoices from pending to paid and creates payment records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--invoice_numbers',
            nargs='+',
            help='List of invoice numbers to transfer',
        )

    def handle(self, *args, **kwargs):
        invoice_numbers = kwargs['invoice_numbers']
        
        if not invoice_numbers:
            self.stdout.write(self.style.ERROR('No invoice numbers provided.'))
            return
        
        for invoice_number in invoice_numbers:
            try:
                # Fetch the GroupedInvoice
                grouped_invoice = GroupedInvoice.objects.get(invoice_number=invoice_number)
                pending_invoice = grouped_invoice.pending_invoice
                
                if pending_invoice and not pending_invoice.is_paid:
                    # Mark the pending invoice as paid
                    pending_invoice.is_paid = True
                    pending_invoice.save()

                    # Create a Payment entry
                    payment = Payment.objects.create(
                        invoice=grouped_invoice,
                        amount=grouped_invoice.total_amount,
                        date=date.today(),
                        method='Shell Command Payment'
                    )

                    self.stdout.write(self.style.SUCCESS(f"Transferred invoice {invoice_number} to paid and created a payment."))
                else:
                    self.stdout.write(self.style.WARNING(f"Invoice {invoice_number} is already marked as paid or not pending."))

            except GroupedInvoice.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"GroupedInvoice with invoice number {invoice_number} does not exist."))

