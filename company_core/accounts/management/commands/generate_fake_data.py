import random
from datetime import timedelta, date
from django.core.management.base import BaseCommand
from faker import Faker
from django.contrib.auth.models import User
from accounts.models import MechExpense, MechExpenseItem

fake = Faker()

# Function to generate random dates within a specific period
def random_date(start, end):
    return start + timedelta(days=random.randint(0, (end - start).days))

class Command(BaseCommand):
    help = 'Generate fake MechExpense and MechExpenseItem data'

    def add_arguments(self, parser):
        # Add arguments to specify the number of records to create
        parser.add_argument('--expenses', type=int, default=10, help='Number of MechExpense records to create')
        parser.add_argument('--items', type=int, default=5, help='Number of MechExpenseItem records per expense')
        parser.add_argument('--start_date', type=str, default="2022-01-01", help='Start date for the data (YYYY-MM-DD)')
        parser.add_argument('--end_date', type=str, default="2024-12-31", help='End date for the data (YYYY-MM-DD)')

    def handle(self, *args, **options):
        num_expenses = options['expenses']
        num_items = options['items']
        start_date = date.fromisoformat(options['start_date'])
        end_date = date.fromisoformat(options['end_date'])

        # Get a random user for assigning to MechExpense (adjust as necessary)
        users = list(User.objects.all())
        if not users:
            self.stdout.write(self.style.ERROR('No users found! Please create a user first.'))
            return

        for _ in range(num_expenses):
            user = random.choice(users)
            vendor = fake.company()
            expense_date = random_date(start_date, end_date)
            receipt_no = fake.unique.numerify(text="REC-#####")

            # Create MechExpense
            mech_expense = MechExpense.objects.create(
                user=user,
                vendor=vendor,
                date=expense_date,
                receipt_no=receipt_no
            )

            # Create MechExpenseItems for each MechExpense
            for _ in range(num_items):
                part_no = fake.unique.bothify(text="PART-###-??")
                description = fake.sentence(nb_words=6)
                qty = round(random.uniform(1, 10), 2)
                price = round(random.uniform(10, 1000), 2)

                # Create MechExpenseItem
                MechExpenseItem.objects.create(
                    mech_expense=mech_expense,
                    part_no=part_no,
                    description=description,
                    qty=qty,
                    price=price,
                )

            self.stdout.write(self.style.SUCCESS(f'Created MechExpense: {mech_expense}'))

        self.stdout.write(self.style.SUCCESS(f'Successfully created {num_expenses} MechExpense records with {num_items} items each.'))
