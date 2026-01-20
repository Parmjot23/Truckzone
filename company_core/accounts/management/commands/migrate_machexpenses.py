from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from blank.models import MachExpense, MachExpenseItem, machExpenses  # Replace with your actual app name

class Command(BaseCommand):
    help = 'Migrate machExpenses data to new MachExpense and MachExpenseItem models'

    def handle(self, *args, **kwargs):
        expenses_grouped = {}

        # Group the old machExpenses entries by user, vendor, and date
        for old_expense in machExpenses.objects.all():
            key = (old_expense.user, old_expense.vendor, old_expense.date)
            if key not in expenses_grouped:
                expenses_grouped[key] = []
            expenses_grouped[key].append(old_expense)

        # Create new MachExpense and MachExpenseItem entries
        for (user, vendor, date), expenses in expenses_grouped.items():
            mach_expense = MachExpense.objects.create(user=user, vendor=vendor, date=date)
            for old_expense in expenses:
                MachExpenseItem.objects.create(
                    mach_expense=mach_expense,
                    part_no=old_expense.part_no,
                    description=old_expense.description,
                    qty=old_expense.qty,
                    price=old_expense.price
                )

        self.stdout.write(self.style.SUCCESS('Successfully migrated machExpenses data'))
