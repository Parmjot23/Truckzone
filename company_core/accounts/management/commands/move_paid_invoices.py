from django.core.management.base import BaseCommand
from django.db import transaction
from blank.models import PendingInvoice, PaidInvoice, IncomeRecord2

class Command(BaseCommand):
    help = 'Update existing PendingInvoice records to PaidInvoice if they are marked as paid.'

    def handle(self, *args, **kwargs):
        pending_invoices = PendingInvoice.objects.filter(is_paid=True)
        
        for pending_invoice in pending_invoices:
            try:
                with transaction.atomic():
                    # Check if a PaidInvoice already exists for the GroupedInvoice
                    paid_invoice, created = PaidInvoice.objects.get_or_create(grouped_invoice=pending_invoice.grouped_invoice)
                    
                    if created:
                        jobs = IncomeRecord2.objects.filter(grouped_invoice=pending_invoice.grouped_invoice)
                        for job in jobs:
                            job.pending_invoice = None
                            job.paid_invoice = paid_invoice
                            job.save()
                        pending_invoice.delete()
                        self.stdout.write(self.style.SUCCESS(f"Invoice {pending_invoice.grouped_invoice.invoice_number} marked as paid and moved to Paid Invoices."))
                    else:
                        self.stdout.write(self.style.WARNING(f"Invoice {pending_invoice.grouped_invoice.invoice_number} is already marked as paid."))
            except IntegrityError:
                transaction.rollback()
                self.stdout.write(self.style.ERROR(f"IntegrityError: Invoice {pending_invoice.grouped_invoice.invoice_number} could not be marked as paid due to a uniqueness constraint."))

        self.stdout.write(self.style.SUCCESS("All marked invoices have been processed."))
