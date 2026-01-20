# accounts/management/commands/populate_vehicle_job_data.py

import logging
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

# Adjust these imports to match your project structure and app name(s)
# Assuming all these models are in the same app 'accounts' or correctly discoverable
from accounts.models import Customer, GroupedInvoice, Vehicle, JobHistory, IncomeRecord2, Product, Driver
# If User is Django's default: from django.contrib.auth.models import User
# If custom user model: from django.conf import settings; User = settings.AUTH_USER_MODEL

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = (
        'Deletes existing Vehicle/JobHistory data, then repopulates from GroupedInvoice/IncomeRecord2, '
        'and updates Customer vehicle_count.'
    )

    @transaction.atomic # Ensures the whole process is atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("--- Starting Data Population Process ---"))

        # Step 0: Delete existing data from Vehicle and JobHistory models
        self.stdout.write(self.style.WARNING("Deleting existing JobHistory records..."))
        job_history_deleted_count, _ = JobHistory.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"  Deleted {job_history_deleted_count} JobHistory records."))

        self.stdout.write(self.style.WARNING("Deleting existing Vehicle records..."))
        vehicle_deleted_count, _ = Vehicle.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"  Deleted {vehicle_deleted_count} Vehicle records."))

        self.stdout.write(self.style.WARNING("Resetting vehicle_count on all Customers..."))
        Customer.objects.all().update(vehicle_count=0)
        self.stdout.write(self.style.SUCCESS("  Customer vehicle_counts reset to 0."))

        vehicles_created = 0
        vehicles_updated = 0
        job_history_records_created = 0
        job_history_skipped_exists = 0
        customers_vehicle_count_updated = 0

        # Step 1: Process Invoices to Create/Update Vehicles and link Job History
        invoices_with_vins = GroupedInvoice.objects.filter(vin_no__isnull=False).exclude(vin_no__exact='').order_by('customer_id', 'date')

        if not invoices_with_vins.exists():
            self.stdout.write(self.style.WARNING("No GroupedInvoices with VIN numbers found to process for vehicles."))
        else:
            self.stdout.write(f"Found {invoices_with_vins.count()} invoices with VINs to process...")

        for invoice in invoices_with_vins.select_related('customer', 'customer__user').prefetch_related('income_records', 'income_records__product', 'income_records__driver'):
            if not invoice.customer:
                self.stdout.write(self.style.WARNING(f"  Skipping Invoice {invoice.invoice_number}: No associated customer."))
                continue

            # Check if the customer for this invoice has a user linked.
            # This is likely why you might see "N/A" for users in the admin.
            if not invoice.customer.user:
                self.stdout.write(self.style.NOTICE( # Using NOTICE style for less alarming warnings
                    f"  Notice: Customer '{invoice.customer.name}' (ID: {invoice.customer.id}) for Invoice {invoice.invoice_number} "
                    f"is not linked to a Django User. Vehicle/JobHistory user will appear as N/A."
                ))

            self.stdout.write(f"\nProcessing Invoice: {invoice.invoice_number} for Customer: {invoice.customer.name} (Customer User: {invoice.customer.user.username if invoice.customer.user else 'N/A'})")

            vin_normalized = invoice.vin_no.strip().upper()
            vehicle_instance = None

            try:
                vehicle_instance, created = Vehicle.objects.get_or_create(
                    vin_number=vin_normalized,
                    defaults={
                        'customer': invoice.customer, # This assigns the vehicle to the invoice's customer
                        'unit_number': invoice.unit_no if invoice.unit_no else '',
                        'make_model': invoice.make_model if invoice.make_model else '',
                    }
                )
                if created:
                    vehicles_created += 1
                    self.stdout.write(self.style.SUCCESS(f"    Created Vehicle: VIN {vin_normalized} for customer '{invoice.customer.name}'"))
                else:
                    if vehicle_instance.customer != invoice.customer:
                        self.stdout.write(self.style.WARNING(
                            f"    Vehicle VIN {vin_normalized} exists but is linked to a different customer "
                            f"('{vehicle_instance.customer.name if vehicle_instance.customer else 'None'}'). "
                            f"Current invoice customer: '{invoice.customer.name}'. VIN ownership not changed. Jobs for this invoice/customer will not be linked to this vehicle instance."
                        ))
                        vehicle_instance = None # Prevent jobs for this invoice being linked to a vehicle owned by another customer
                    else:
                        # Vehicle exists and customer matches, optionally update details
                        updated = False
                        if invoice.unit_no and vehicle_instance.unit_number != invoice.unit_no:
                            vehicle_instance.unit_number = invoice.unit_no
                            updated = True
                        if invoice.make_model and vehicle_instance.make_model != invoice.make_model:
                            vehicle_instance.make_model = invoice.make_model
                            updated = True
                        if updated:
                            vehicle_instance.save()
                            vehicles_updated +=1
                            self.stdout.write(f"      Updated details for existing Vehicle: VIN {vin_normalized}")
                        else:
                            self.stdout.write(f"      Confirmed existing Vehicle: VIN {vin_normalized} for customer '{invoice.customer.name}'")

                # Step 2: Create JobHistory records from IncomeRecord2 for this vehicle/invoice
                if vehicle_instance: # Only if vehicle_instance is valid and linked to the correct customer
                    for income_record in invoice.income_records.all():
                        if JobHistory.objects.filter(source_income_record=income_record).exists():
                            job_history_skipped_exists += 1
                            # self.stdout.write(f"      JobHistory for IncomeRecord ID {income_record.id} already exists. Skipping.") # Can be verbose
                            continue

                        job_date_to_use = income_record.date if income_record.date else invoice.date
                        if not job_date_to_use:
                            self.stdout.write(self.style.WARNING(f"      Skipping IncomeRecord ID {income_record.id} for Invoice {invoice.invoice_number}: No date available."))
                            continue

                        description = income_record.job
                        if not description and income_record.product:
                            description = f"Product: {income_record.product.name if income_record.product else 'N/A'}"
                        if not description:
                            description = "No description provided"

                        notes_list = []
                        if income_record.ticket: notes_list.append(f"Ticket: {income_record.ticket}")
                        if income_record.jobsite: notes_list.append(f"Jobsite: {income_record.jobsite}")
                        if income_record.truck: notes_list.append(f"Truck: {income_record.truck}")
                        if income_record.driver: notes_list.append(f"Driver: {income_record.driver.name if income_record.driver else 'N/A'}")
                        job_notes = "; ".join(notes_list)

                        JobHistory.objects.create(
                            vehicle=vehicle_instance,
                            invoice=invoice,
                            source_income_record=income_record,
                            job_date=job_date_to_use,
                            description=description,
                            service_cost=income_record.amount if income_record.amount is not None else Decimal('0.00'),
                            tax_amount=income_record.tax_collected if income_record.tax_collected is not None else Decimal('0.00'),
                            notes=job_notes
                        )
                        job_history_records_created += 1
                        # self.stdout.write(self.style.SUCCESS(f"      Created JobHistory for: {description[:40]}...")) # Can be verbose
                    if invoice.income_records.count() > 0 and job_history_records_created > 0 : # Basic check if jobs were processed for this invoice
                         self.stdout.write(self.style.SUCCESS(f"      Processed {invoice.income_records.count()} income records for JobHistory for Invoice {invoice.invoice_number}."))


                elif invoice.vin_no: # Only log if VIN was present but vehicle_instance ended up None
                     self.stdout.write(f"    Skipping JobHistory creation for invoice {invoice.invoice_number} as vehicle assignment was problematic (e.g. VIN owned by different customer).")


            except Exception as e:
                logger.error(f"Error processing Invoice {invoice.invoice_number} or its items: {e}", exc_info=True)
                self.stderr.write(self.style.ERROR(f"  Error processing Invoice {invoice.invoice_number}: {e}"))

        # Step 3: Update vehicle_count for all customers
        self.stdout.write("\nUpdating vehicle counts for all customers...")
        all_customers = Customer.objects.all()
        for customer_obj in all_customers: # Renamed to avoid conflict with 'customer' variable in loop
            original_count = customer_obj.vehicle_count
            new_count = customer_obj.update_vehicle_count()
            if original_count != new_count:
                customers_vehicle_count_updated +=1
        self.stdout.write(f"  Vehicle counts updated for {customers_vehicle_count_updated} customers (where changed).")


        self.stdout.write(self.style.SUCCESS(f"\n--- Data Population Complete ---"))
        self.stdout.write(f"Vehicles Created: {vehicles_created}")
        self.stdout.write(f"Vehicles Details Updated: {vehicles_updated}")
        self.stdout.write(f"Job History Records Created: {job_history_records_created}")
        self.stdout.write(f"Job History Records Skipped (already exist): {job_history_skipped_exists}")
        self.stdout.write(f"Customer Vehicle Counts Updated (where changed): {customers_vehicle_count_updated} (Total customers checked: {all_customers.count()})")