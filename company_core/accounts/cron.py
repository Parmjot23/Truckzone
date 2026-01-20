from django_cron import CronJobBase, Schedule
from django.utils import timezone
from .models import MechExpense, MechExpenseItem
from .utils import calculate_next_occurrence  # Assume calculate_next_occurrence is moved to utils.py
import logging

logger = logging.getLogger(__name__)

class ProcessRecurringExpensesCronJob(CronJobBase):
    RUN_EVERY_MINS = 60 * 24  # Every 24 hours

    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = 'accounts.process_recurring_expenses_cron_job'  # Unique code

    def do(self):
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
