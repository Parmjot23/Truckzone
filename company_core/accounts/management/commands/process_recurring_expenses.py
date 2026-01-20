# your_app/management/commands/process_recurring_expenses.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import MechExpense, MechExpenseItem
from accounts.utils import calculate_next_occurrence
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process recurring expenses and create new entries as needed.'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        recurring_expenses = MechExpense.objects.filter(
            is_recurring=True,
            next_occurrence__lte=today
        )
        logger.info(f"Found {recurring_expenses.count()} recurring expenses to process.")

        for expense in recurring_expenses:
            try:
                original_pk = expense.pk  # Store original PK

                # Create a copy of the expense
                expense.pk = None  # This will create a new instance
                expense.date = expense.next_occurrence
                expense.next_occurrence = calculate_next_occurrence(expense.date, expense.frequency)
                expense.receipt_no = None  # Reset receipt_no to allow auto-generation
                expense.save()
                logger.info(f"Created new expense from receipt {expense.receipt_no} for date {expense.date}.")

                # Copy associated items
                original_items = MechExpenseItem.objects.filter(mech_expense_id=original_pk)
                for item in original_items:
                    item.pk = None
                    item.mech_expense = expense
                    item.save()
                logger.info(f"Copied {original_items.count()} items for new expense.")

                # Update the original expense's next_occurrence
                original_expense = MechExpense.objects.get(pk=original_pk)
                original_expense.next_occurrence = expense.next_occurrence
                original_expense.save()
                logger.info(f"Updated next_occurrence for original expense {original_pk} to {original_expense.next_occurrence}.")

            except Exception as e:
                logger.error(f"Error processing expense {expense.pk}: {e}")