from django.core.management.base import BaseCommand
from faker import Faker
from datetime import datetime, timedelta
import random
from accounts.models import GroupedInvoice, PaidInvoice, IncomeRecord2, Profile
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Generate fake data for PaidInvoice and related models'

    # Define a static list of vehicle makes
    VEHICLE_MAKES = [
        'Ford', 'Chevrolet', 'Toyota', 'Honda', 'Nissan', 'BMW', 'Mercedes-Benz', 'Hyundai', 'Kia', 'Volkswagen'
    ]

    def handle(self, *args, **kwargs):
        # Use Faker to generate fake data
        fake = Faker()

        # Fetch Parm's user account (assuming username is 'parm')
        try:
            user = User.objects.get(username='parm')
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR('User "parm" not found!'))
            return

        # Get user profile
        user_profile = Profile.objects.get(user=user)

        # Generate invoices for the past 2 years
        start_date = datetime.now() - timedelta(days=730)  # 2 years ago
        current_date = datetime.now()

        while start_date <= current_date:
            # Generate a random invoice date within the current month
            invoice_date = start_date + timedelta(days=random.randint(0, 30))

            # Randomly select a vehicle make from the list
            make_model = random.choice(self.VEHICLE_MAKES)

            # Create GroupedInvoice
            grouped_invoice = GroupedInvoice.objects.create(
                user=user,
                date=invoice_date,
                bill_to=fake.company(),
                bill_to_email=fake.email(),
                vin_no=fake.bothify(text='VIN????'),  # Fake VIN number
                mileage=random.randint(10000, 200000),
                unit_no=fake.bothify(text='UNIT####'),  # Fake unit number
                make_model=make_model,  # Use random vehicle make
                total_amount=0.0  # Will be recalculated based on jobs
            )

            # Create PaidInvoice
            paid_invoice = PaidInvoice.objects.create(
                grouped_invoice=grouped_invoice,
                date_paid=invoice_date + timedelta(days=random.randint(1, 30))  # Random payment date after invoice
            )

            # Create IncomeRecord2 linked to the PaidInvoice
            total_amount = 0.0
            for _ in range(random.randint(1, 5)):  # Random number of jobs per invoice
                qty = random.randint(1, 10)
                rate = random.uniform(50.0, 500.0)
                amount = qty * rate
                tax_collected = amount * 0.13  # Assuming 13% tax rate (adjust as needed)

                income_record = IncomeRecord2.objects.create(
                    grouped_invoice=grouped_invoice,
                    paid_invoice=paid_invoice,
                    job=fake.job(),
                    qty=qty,
                    rate=rate,
                    amount=amount,
                    tax_collected=tax_collected,
                    date=invoice_date
                )
                total_amount += amount + tax_collected

            # Update GroupedInvoice total amount
            grouped_invoice.total_amount = round(total_amount, 2)
            grouped_invoice.save()

            # Increment start_date to next month
            start_date += timedelta(days=30)

        self.stdout.write(self.style.SUCCESS('Successfully generated fake data for 2 years!'))
