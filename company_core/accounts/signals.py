from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
import logging
from .models import (
    Profile,
    IncomeRecord2,
    JobHistory,
    Vehicle,
    Customer,
    GroupedInvoice,
    WorkOrder,
    Product,
    InventoryTransaction,
    ActivityLog,
    VehicleMaintenanceTask,
)
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth import logout
from django.shortcuts import redirect
from decimal import Decimal
from django.db import transaction
from .activity import get_current_actor
from .utils import get_business_user


logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_or_save_profile(sender, instance, created, **kwargs):
    """
    Create a profile for a new user or save the profile if the user is updated.
    """
    if created:
        Profile.objects.get_or_create(user=instance)
        return

    if not Profile.objects.filter(user=instance).exists():
        Profile.objects.create(user=instance)


@receiver(user_logged_in)
def check_user_status(sender, user, request, **kwargs):
    """
    Check if the user is active upon login. If not, log the user out and redirect.
    """
    if not user.is_active:
        # Log the user out and redirect to the logout page or another page
        logout(request)
        request.session['redirect_after_logout'] = True  # Set a session variable to track redirection


# ---------- Helpers ---------------------------------------------------------

def _normalise_vin(vin: str) -> str:
    return vin.strip().upper() if vin else ""

def _get_or_create_vehicle(invoice) -> Vehicle | None:
    """
    Return a Vehicle that is owned by the same customer as the invoice.
    • Creates one if it doesn't exist.
    • If the VIN exists for a different customer, returns None
      (we do NOT re‑assign ownership across customers).
    """
    vin = _normalise_vin(invoice.vin_no)
    if not vin or not invoice.customer:
        return None

    # VIN uniqueness is enforced per-customer (not global), so we must scope lookup
    # by both VIN + customer. Otherwise get_or_create(vin=...) can raise
    # MultipleObjectsReturned when the same VIN exists under different customers.
    customer_vehicle_qs = Vehicle.objects.filter(
        customer=invoice.customer,
        vin_number__iexact=vin,
    ).order_by("id")

    created = False
    vehicle = customer_vehicle_qs.first()

    # VIN exists for another customer but not for this customer -> skip to avoid cross-contamination
    if vehicle is None:
        vin_elsewhere = Vehicle.objects.filter(vin_number__iexact=vin).exclude(customer=invoice.customer).exists()
        if vin_elsewhere:
            return None
        vehicle = Vehicle.objects.create(
            customer=invoice.customer,
            vin_number=vin,
            unit_number=invoice.unit_no or "",
            make_model=invoice.make_model or "",
        )
        created = True

    # Different customer owns this VIN – skip to avoid cross‑contamination
    if not created and vehicle.customer_id != invoice.customer_id:
        return None

    # Keep details fresh
    dirty = False
    if invoice.unit_no and vehicle.unit_number != invoice.unit_no:
        vehicle.unit_number = invoice.unit_no
        dirty = True
    if invoice.make_model and vehicle.make_model != invoice.make_model:
        vehicle.make_model = invoice.make_model
        dirty = True
    if dirty:
        vehicle.save(update_fields=["unit_number", "make_model"])
    return vehicle


def _build_notes(record: IncomeRecord2) -> str:
    """
    Craft a single, human‑readable note describing what happened.
    Falls back gracefully when data is missing.
    """
    parts: list[str] = []

    # 1)  Core job / product info
    if record.job:
        parts.append(record.job.capitalize())
    elif record.product:
        # “Replaced oil filter (Qty 1)”
        qty = f"{record.qty.normalize():g}" if record.qty else "1"
        parts.append(f"Installed {record.product.name} (x{qty})")

# ---------- post_save -------------------------------------------------------

@receiver(post_save, sender=IncomeRecord2)
def sync_job_history(sender, instance: IncomeRecord2, **kwargs):
    """
    Create OR update the related JobHistory row every time an IncomeRecord2
    is saved.  We run it AFTER the outer transaction commits to avoid
    race‑conditions inside views that wrap everything in @transaction.atomic.
    """
    def _sync():
        invoice = instance.grouped_invoice
        if not invoice:
            return

        vehicle = _get_or_create_vehicle(invoice)
        if not vehicle:
            # No valid vehicle → silently skip.  You can log here if desired.
            return

        job_date = instance.date or invoice.date
        if not job_date:
            return                         # Nothing to file without a date

        description = (
            instance.job
            or (f"Product: {instance.product.name}" if instance.product else "")
            or "No description provided"
        )

        obj, _ = JobHistory.objects.update_or_create(
            source_income_record=instance,
            defaults={
                "vehicle": vehicle,
                "invoice": invoice,
                "job_date": job_date,
                "description": description,
                "service_cost": instance.amount or Decimal("0.00"),
                "tax_amount": instance.tax_collected or Decimal("0.00"),
                "notes": _build_notes(instance),
            },
        )
    transaction.on_commit(_sync)

# ---------- post_delete -----------------------------------------------------

@receiver(post_delete, sender=IncomeRecord2)
def delete_job_history(sender, instance: IncomeRecord2, **kwargs):
    """
    When a line‑item disappears we wipe the associated JobHistory row.
    """
    def _purge():
        JobHistory.objects.filter(source_income_record=instance).delete()
    transaction.on_commit(_purge)



# ────────────────────────────────────────────────────────────────────────────
# VEHICLE ⇆ CUSTOMER COUNT
# ────────────────────────────────────────────────────────────────────────────

@receiver(pre_save, sender=Vehicle)
def _cache_old_customer(sender, instance: Vehicle, **kwargs):
    """
    Before saving, stash the previous customer ID (if any) so we can
    adjust counts when a vehicle gets reassigned.
    """
    if instance.pk:
        try:
            instance._old_customer_id = (
                sender.objects.only("customer_id")
                .get(pk=instance.pk)
                .customer_id
            )
        except sender.DoesNotExist:
            instance._old_customer_id = None


@receiver(post_save, sender=Vehicle)
def _update_vehicle_counts_on_save(sender, instance: Vehicle, created, **kwargs):
    """
    After every save we touch **both** the new customer and, if the
    vehicle was reassigned, the old customer.
    """
    instance.customer.update_vehicle_count()

    old_id = getattr(instance, "_old_customer_id", None)
    if old_id and old_id != instance.customer_id:
        try:
            Customer.objects.get(pk=old_id).update_vehicle_count()
        except Customer.DoesNotExist:
            pass  # old customer was deleted – ignore


@receiver(post_delete, sender=Vehicle)
def _update_vehicle_count_on_delete(sender, instance: Vehicle, **kwargs):
    """
    Drop the count when a vehicle disappears.
    """
    if instance.customer_id:
        instance.customer.update_vehicle_count()

# ────────────────────────────────────────────────────────────────────────────
# BUSINESS ACTIVITY LOGGING
# ────────────────────────────────────────────────────────────────────────────

def _record_activity(instance, *, action, object_type, description, object_id=None, metadata=None):
    actor = get_current_actor()
    if not actor or not actor.is_authenticated:
        return

    actor_profile = getattr(actor, "profile", None)
    if not actor_profile or not actor_profile.is_business_admin or not actor_profile.admin_approved:
        return

    business_user = None
    instance_user = getattr(instance, "user", None)
    if instance_user:
        business_user = instance_user
    elif object_type == "inventory_transaction" and getattr(instance, "product", None):
        business_user = instance.product.user

    business_user = business_user or get_business_user(actor)
    if not business_user:
        return

    ActivityLog.objects.create(
        business=business_user,
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id or getattr(instance, "pk", "")),
        description=description,
        metadata=metadata or {},
    )


@receiver(post_save, sender=GroupedInvoice)
def log_grouped_invoice_activity(sender, instance: GroupedInvoice, created: bool, **kwargs):
    def _sync_inventory():
        try:
            instance.ensure_inventory_transactions()
        except Exception:
            logger.exception(
                "Failed to ensure inventory transactions for invoice %s",
                getattr(instance, "invoice_number", instance.pk),
            )
    transaction.on_commit(_sync_inventory)

    identifier = getattr(instance, "invoice_number", None) or instance.pk
    action = "created" if created else "updated"
    metadata = {}
    if instance.customer_id and instance.customer:
        metadata["customer"] = instance.customer.name
    description = f"Invoice {identifier} {action}"
    _record_activity(
        instance,
        action=f"invoice_{action}",
        object_type="invoice",
        description=description,
        object_id=identifier,
        metadata=metadata,
    )


@receiver(post_delete, sender=GroupedInvoice)
def log_grouped_invoice_delete(sender, instance: GroupedInvoice, **kwargs):
    identifier = getattr(instance, "invoice_number", None) or instance.pk
    metadata = {}
    if instance.customer_id and getattr(instance, "customer", None):
        metadata["customer"] = instance.customer.name

    VehicleMaintenanceTask.objects.filter(
        grouped_invoice=instance,
        status__in=VehicleMaintenanceTask.ACTIVE_STATUSES,
    ).update(status=VehicleMaintenanceTask.STATUS_CANCELLED)

    _record_activity(
        instance,
        action="invoice_deleted",
        object_type="invoice",
        description=f"Invoice {identifier} deleted",
        object_id=identifier,
        metadata=metadata,
    )


@receiver(post_save, sender=IncomeRecord2)
def ensure_inventory_for_line(sender, instance: IncomeRecord2, created: bool, **kwargs):
    invoice = getattr(instance, "grouped_invoice", None)
    if not invoice:
        return
    def _sync_inventory():
        try:
            invoice.ensure_inventory_transactions()
        except Exception:
            logger.exception(
                "Failed to backfill inventory for IncomeRecord2 #%s on invoice %s",
                instance.pk,
                getattr(invoice, "invoice_number", getattr(invoice, "pk", "")),
            )
    transaction.on_commit(_sync_inventory)


@receiver(post_save, sender=WorkOrder)
def log_workorder_activity(sender, instance: WorkOrder, created: bool, **kwargs):
    identifier = instance.pk
    action = "created" if created else "updated"
    metadata = {}
    if instance.customer_id and instance.customer:
        metadata["customer"] = instance.customer.name
    description = f"Work order #{identifier} {action}"
    _record_activity(
        instance,
        action=f"workorder_{action}",
        object_type="workorder",
        description=description,
        object_id=identifier,
        metadata=metadata,
    )


@receiver(post_delete, sender=WorkOrder)
def log_workorder_delete(sender, instance: WorkOrder, **kwargs):
    identifier = instance.pk
    metadata = {}
    if instance.customer_id and getattr(instance, "customer", None):
        metadata["customer"] = instance.customer.name

    VehicleMaintenanceTask.objects.filter(
        work_order=instance,
        status__in=VehicleMaintenanceTask.ACTIVE_STATUSES,
    ).update(status=VehicleMaintenanceTask.STATUS_CANCELLED)

    _record_activity(
        instance,
        action="workorder_deleted",
        object_type="workorder",
        description=f"Work order #{identifier} deleted",
        object_id=identifier,
        metadata=metadata,
    )


@receiver(post_save, sender=Product)
def log_product_activity(sender, instance: Product, created: bool, **kwargs):
    action = "created" if created else "updated"
    identifier = instance.sku or instance.pk
    metadata = {"sku": instance.sku or "", "name": instance.name}
    description = f"Product {instance.name} {action}"
    _record_activity(
        instance,
        action=f"product_{action}",
        object_type="product",
        description=description,
        object_id=identifier,
        metadata=metadata,
    )


@receiver(post_delete, sender=Product)
def log_product_delete(sender, instance: Product, **kwargs):
    identifier = instance.sku or instance.pk
    metadata = {"sku": instance.sku or "", "name": instance.name}
    _record_activity(
        instance,
        action="product_deleted",
        object_type="product",
        description=f"Product {instance.name} deleted",
        object_id=identifier,
        metadata=metadata,
    )


@receiver(post_save, sender=InventoryTransaction)
def log_inventory_transaction(sender, instance: InventoryTransaction, created: bool, **kwargs):
    # Skip logging when loading fixtures or other "raw" operations.
    if kwargs.get("raw"):
        return
    if not created:
        return
    product_name = instance.product.name if instance.product else ""
    metadata = {
        "product": product_name,
        "quantity": instance.quantity,
        "transaction_type": instance.transaction_type,
    }
    description = (
        f"Inventory transaction {instance.get_transaction_type_display()} "
        f"for {product_name} ({instance.quantity})"
    )
    _record_activity(
        instance,
        action="inventory_transaction_created",
        object_type="inventory_transaction",
        description=description.strip(),
        object_id=instance.pk,
        metadata=metadata,
    )


@receiver(post_delete, sender=InventoryTransaction)
def log_inventory_transaction_delete(sender, instance: InventoryTransaction, **kwargs):
    product_name = instance.product.name if instance.product else ""
    metadata = {
        "product": product_name,
        "quantity": instance.quantity,
        "transaction_type": instance.transaction_type,
    }
    _record_activity(
        instance,
        action="inventory_transaction_deleted",
        object_type="inventory_transaction",
        description=f"Inventory transaction removed for {product_name}",
        object_id=instance.pk,
        metadata=metadata,
    )
