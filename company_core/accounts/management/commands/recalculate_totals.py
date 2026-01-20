from django.core.management.base import BaseCommand
from accounts.models import GroupedInvoice

class Command(BaseCommand):
    help = 'Recalculates total amount for all GroupedInvoice instances'

    def handle(self, *args, **kwargs):
        invoices = GroupedInvoice.objects.all()
        for invoice in invoices:
            invoice.recalculate_total_amount()
            self.stdout.write(self.style.SUCCESS(f'Recalculated total for invoice {invoice.id} - ${invoice.total_amount:.2f}'))