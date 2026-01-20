from django.core.management.base import BaseCommand
from blank.models import GroupedInvoice

class Command(BaseCommand):
    help = 'Recalculate total amounts for all grouped invoices and delete those with total amount effectively zero'

    def handle(self, *args, **kwargs):
        threshold = 0.01
        invoices = GroupedInvoice.objects.all()
        for invoice in invoices:
            invoice.total_amount = sum(job.amount for job in invoice.income_records.all())
            if abs(invoice.total_amount) < threshold:
                self.stdout.write(self.style.WARNING(f'Deleting invoice {invoice.invoice_number} with total amount {invoice.total_amount}'))
                invoice.delete()
            else:
                invoice.save()
        self.stdout.write(self.style.SUCCESS('Successfully updated invoice totals'))
