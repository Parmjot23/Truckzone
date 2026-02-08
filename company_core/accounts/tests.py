from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import CustomerForm, VehicleQuickWorkOrderForm
from .models import (
    Customer,
    GroupedInvoice,
    IncomeRecord2,
    InventoryTransaction,
    Mechanic,
    Product,
    Profile,
    Supplier,
    Vehicle,
    VehicleMaintenanceTask,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderRecord,
)
from .utils import sync_workorder_assignments


class WorkOrderInventoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.customer = Customer.objects.create(user=self.user, name="C")
        self.product = Product.objects.create(
            user=self.user,
            sku="SKU",
            name="Prod",
            cost_price=Decimal("5.00"),
            sale_price=Decimal("10.00"),
            quantity_in_stock=10,
        )

    def test_workorder_completion_posts_inventory(self):
        wo = WorkOrder.objects.create(
            user=self.user,
            customer=self.customer,
            status="pending",
            scheduled_date=timezone.now().date(),
        )
        WorkOrderRecord.objects.create(
            work_order=wo,
            product=self.product,
            qty=Decimal("2"),
            rate=Decimal("10.00"),
        )

        wo.status = "completed"
        wo.save()

        self.assertIsNotNone(wo.invoice)
        trans = InventoryTransaction.objects.filter(product=self.product)
        self.assertEqual(trans.count(), 1)
        self.assertEqual(trans.first().transaction_type, "OUT")
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 8)

        wo.invoice.delete()

        self.product.refresh_from_db()
        trans = InventoryTransaction.objects.filter(product=self.product)
        # Should have one OUT and one IN
        self.assertEqual(trans.count(), 2)
        self.assertEqual(
            trans.latest("id").transaction_type,
            "IN",
        )
        self.assertEqual(self.product.quantity_in_stock, 10)

    def test_workorder_completion_surfaces_insufficient_inventory(self):
        self.product.quantity_in_stock = 0
        self.product.save()

        wo = WorkOrder.objects.create(
            user=self.user,
            customer=self.customer,
            status="pending",
            scheduled_date=timezone.now().date(),
        )
        WorkOrderRecord.objects.create(
            work_order=wo,
            product=self.product,
            qty=Decimal("1"),
            rate=Decimal("10.00"),
        )

        wo.status = "completed"
        with self.assertRaises(ValidationError) as ctx:
            wo.save()

        self.assertIn(
            "Not enough inventory",
            ctx.exception.message_dict["inventory"][0],
        )

    def test_workorder_and_invoice_share_sequence_number(self):
        GroupedInvoice.objects.create(user=self.user, customer=self.customer)
        expected_number = GroupedInvoice.generate_invoice_number(self.user, commit=False)
        wo = WorkOrder.objects.create(
            user=self.user,
            customer=self.customer,
            status="pending",
            scheduled_date=timezone.now().date(),
        )

        wo.status = "completed"
        wo.save()

        self.assertIsNotNone(wo.invoice)
        self.assertEqual(wo.invoice.invoice_number, expected_number)
        sequence = expected_number.rsplit("-", 1)[-1]
        self.assertEqual(wo.workorder_number, f"WO-{sequence}")

    def test_product_margin_auto_calculated(self):
        self.assertEqual(self.product.margin, Decimal("5.00"))



class InvoiceProductSaleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="invuser", password="p")
        self.customer = Customer.objects.create(user=self.user, name="Cust")
        self.product = Product.objects.create(
            user=self.user,
            sku="SKU2",
            name="Prod2",
            cost_price=Decimal("5.00"),
            sale_price=Decimal("10.00"),
            quantity_in_stock=10,
        )

    def test_invoice_product_sale_creates_stock_out(self):
        invoice = GroupedInvoice.objects.create(user=self.user, customer=self.customer)
        line = IncomeRecord2.objects.create(
            grouped_invoice=invoice,
            product=self.product,
            qty=Decimal("3"),
            rate=Decimal("10.00"),
        )
        trans = InventoryTransaction.objects.filter(product=self.product)
        self.assertEqual(trans.count(), 1)
        self.assertEqual(trans.first().transaction_type, "OUT")

    def test_ensure_inventory_transactions_backfills_missing_entries(self):
        invoice = GroupedInvoice.objects.create(user=self.user, customer=self.customer)
        IncomeRecord2.objects.create(
            grouped_invoice=invoice,
            product=self.product,
            qty=Decimal("2"),
            rate=Decimal("10.00"),
        )
        IncomeRecord2.objects.create(
            grouped_invoice=invoice,
            product=self.product,
            qty=Decimal("3"),
            rate=Decimal("10.00"),
        )

        # Simulate a scenario where stock deductions failed to record
        InventoryTransaction.objects.all().delete()
        self.product.quantity_in_stock = 10
        self.product.save(update_fields=["quantity_in_stock"])

        invoice.ensure_inventory_transactions()

        trans = InventoryTransaction.objects.filter(product=self.product, transaction_type="OUT")
        self.assertEqual(trans.count(), 1)
        self.assertEqual(trans.first().quantity, 5)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity_in_stock, 5)


class InvoiceInventoryEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="edituser", password="p")
        self.customer = Customer.objects.create(user=self.user, name="Cust")
        self.product1 = Product.objects.create(
            user=self.user,
            sku="P1",
            name="Prod1",
            cost_price=Decimal("5.00"),
            sale_price=Decimal("10.00"),
            quantity_in_stock=10,
        )
        self.product2 = Product.objects.create(
            user=self.user,
            sku="P2",
            name="Prod2",
            cost_price=Decimal("3.00"),
            sale_price=Decimal("6.00"),
            quantity_in_stock=5,
        )

    def test_edit_and_delete_updates_stock(self):
        invoice = GroupedInvoice.objects.create(user=self.user, customer=self.customer)
        line = IncomeRecord2.objects.create(
            grouped_invoice=invoice,
            product=self.product1,
            qty=Decimal("2"),
            rate=Decimal("10.00"),
        )

        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity_in_stock, 8)

        # Change quantity on the same product
        line.qty = Decimal("3")
        line.save()

        self.product1.refresh_from_db()
        self.assertEqual(self.product1.quantity_in_stock, 7)

        # Change to a different product
        line.product = self.product2
        line.qty = Decimal("1")
        line.save()

        self.product1.refresh_from_db()
        self.product2.refresh_from_db()
        self.assertEqual(self.product1.quantity_in_stock, 10)
        self.assertEqual(self.product2.quantity_in_stock, 4)

        invoice.delete()

        self.product2.refresh_from_db()
        self.assertEqual(self.product2.quantity_in_stock, 5)

        # Verify transactions were recorded
        p1_trans = InventoryTransaction.objects.filter(product=self.product1)
        p2_trans = InventoryTransaction.objects.filter(product=self.product2)
        self.assertEqual(p1_trans.count(), 4)
        self.assertEqual(p2_trans.count(), 2)


class WorkOrderAssignmentSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="assigner", password="p")
        self.customer = Customer.objects.create(user=self.user, name="Fleet")
        self.workorder = WorkOrder.objects.create(
            user=self.user,
            customer=self.customer,
            status="pending",
            scheduled_date=timezone.now().date(),
        )
        self.mechanic_a = Mechanic.objects.create(user=self.user, name="Alex")
        self.mechanic_b = Mechanic.objects.create(user=self.user, name="Blake")

    def test_sync_assignments_creates_multiple_rows(self):
        result = sync_workorder_assignments(self.workorder, [self.mechanic_a, self.mechanic_b])
        self.assertEqual(self.workorder.assignments.count(), 2)
        self.assertEqual(len(result["created"]), 2)

    def test_sync_assignments_removes_unsubmitted(self):
        WorkOrderAssignment.objects.create(workorder=self.workorder, mechanic=self.mechanic_a)
        result = sync_workorder_assignments(self.workorder, [])
        self.assertEqual(self.workorder.assignments.count(), 0)
        self.assertEqual(len(result["removed"]), 1)
        self.assertFalse(result["protected"])

    def test_sync_assignments_protects_submitted(self):
        WorkOrderAssignment.objects.create(workorder=self.workorder, mechanic=self.mechanic_a, submitted=True)
        result = sync_workorder_assignments(self.workorder, [])
        self.assertEqual(self.workorder.assignments.count(), 1)
        self.assertEqual(len(result["protected"]), 1)


@override_settings(SITE_URL="http://example.com")
class WorkOrderReworkRequestTests(TestCase):
    def setUp(self):
        self.business = User.objects.create_user(username="owner", password="pass123", email="owner@example.com")
        self.profile = Profile.objects.create(
            user=self.business,
            occupation="truck_mechanic",
            activation_link_clicked=True,
        )
        self.customer = Customer.objects.create(user=self.business, name="FleetCo")
        self.workorder = WorkOrder.objects.create(
            user=self.business,
            customer=self.customer,
            status="pending",
            scheduled_date=timezone.localdate(),
        )
        self.mechanic = Mechanic.objects.create(
            user=self.business,
            name="Casey",
            email="casey@example.com",
        )
        self.assignment = WorkOrderAssignment.objects.create(
            workorder=self.workorder,
            mechanic=self.mechanic,
            submitted=True,
        )

    def test_request_rework_marks_assignment_and_sends_email(self):
        self.client.force_login(self.business)
        url = reverse(
            "accounts:workorder_assignment_reopen",
            args=[self.workorder.pk, self.assignment.pk],
        )
        response = self.client.post(
            url,
            {f"reassign-{self.assignment.pk}-instructions": "Please include detailed cause and correction notes."},
        )

        self.assertRedirects(response, reverse("accounts:workorder_detail", args=[self.workorder.pk]))

        assignment = WorkOrderAssignment.objects.get(pk=self.assignment.pk)
        self.assertTrue(assignment.requires_rework)
        self.assertFalse(assignment.submitted)
        self.assertIsNone(assignment.date_submitted)
        self.assertIsNotNone(assignment.rework_requested_at)
        self.assertEqual(
            assignment.rework_instructions,
            "Please include detailed cause and correction notes.",
        )

        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.mechanic_status, "in_progress")

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("URGENT", email.subject)
        self.assertIn("Please include detailed cause and correction notes.", email.body)
        self.assertIn("http://example.com/workorders/fill/", email.body)
        self.assertIn(assignment.assignment_token, email.body)


class VehicleQuickWorkOrderFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="fleetowner", password="p")
        self.mechanic_a = Mechanic.objects.create(user=self.user, name="Taylor")
        self.mechanic_b = Mechanic.objects.create(user=self.user, name="Jordan")

    def test_requires_at_least_one_mechanic(self):
        data = {
            "scheduled_date": timezone.localdate().isoformat(),
            "mechanics": [],
        }
        form = VehicleQuickWorkOrderForm(data=data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("mechanics", form.errors)
        self.assertIn("Please select at least one mechanic.", form.errors["mechanics"])

    def test_accepts_multiple_mechanics(self):
        data = {
            "scheduled_date": timezone.localdate().isoformat(),
            "mechanics": [str(self.mechanic_a.id), str(self.mechanic_b.id)],
        }
        form = VehicleQuickWorkOrderForm(data=data, user=self.user)
        self.assertTrue(form.is_valid())
        selected = {mechanic.pk for mechanic in form.cleaned_data["mechanics"]}
        self.assertSetEqual(selected, {self.mechanic_a.pk, self.mechanic_b.pk})


class CustomerPortalFormTests(TestCase):
    def setUp(self):
        self.business = User.objects.create_user(username="owner", password="pass123")
        self.profile = Profile.objects.create(user=self.business, occupation="truck_mechanic", province="ON")

    def test_creates_portal_user_when_enabled(self):
        form = CustomerForm(
            data={
                "name": "Acme Logistics",
                "email": "client@example.com",
                "address": "123 Fleet Street",
                "phone_number": "",
                "gst_hst_number": "",
                "charge_rate": "",
                "register_portal": True,
                "portal_username": "acme_portal",
                "portal_password": "TempPass123!",
            },
            user=self.business,
        )
        self.assertTrue(form.is_valid(), form.errors)
        customer = form.save()
        self.assertEqual(customer.user, self.business)
        self.assertIsNotNone(customer.portal_user)
        self.assertEqual(customer.portal_user.username, "acme_portal")
        self.assertTrue(customer.portal_user.is_active)
        self.assertTrue(customer.portal_user.check_password("TempPass123!"))

    def test_disable_portal_marks_user_inactive(self):
        portal_user = User.objects.create_user(username="disableme", password="OldPass!1")
        customer = Customer.objects.create(user=self.business, name="Disable Co", portal_user=portal_user)
        form = CustomerForm(
            data={
                "name": "Disable Co",
                "email": "",
                "address": "",
                "phone_number": "",
                "gst_hst_number": "",
                "charge_rate": "",
                "register_portal": False,
                "portal_username": "disableme",
                "portal_password": "",
            },
            instance=customer,
            user=self.business,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        portal_user.refresh_from_db()
        customer.refresh_from_db()
        self.assertFalse(portal_user.is_active)
        self.assertEqual(customer.portal_user, portal_user)

    def test_update_username_and_password(self):
        portal_user = User.objects.create_user(username="oldname", password="OldPass!1")
        customer = Customer.objects.create(user=self.business, name="Update Co", portal_user=portal_user, email="update@example.com")
        form = CustomerForm(
            data={
                "name": "Update Co",
                "email": "update@example.com",
                "address": "",
                "phone_number": "",
                "gst_hst_number": "",
                "charge_rate": "",
                "register_portal": True,
                "portal_username": "newname",
                "portal_password": "NewPass!234",
            },
            instance=customer,
            user=self.business,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        portal_user.refresh_from_db()
        customer.refresh_from_db()
        self.assertEqual(portal_user.username, "newname")
        self.assertTrue(portal_user.is_active)
        self.assertTrue(portal_user.check_password("NewPass!234"))


class PortalDecoratorRedirectTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.general_user = User.objects.create_user(username="general", password="pass")
        self.customer_user = User.objects.create_user(username="customer", password="pass")
        self.supplier_user = User.objects.create_user(username="supplier", password="pass")

        self.customer = Customer.objects.create(
            user=self.owner,
            name="Customer Co",
            portal_user=self.customer_user,
        )
        self.supplier = Supplier.objects.create(
            user=self.owner,
            name="Supplier Co",
            portal_user=self.supplier_user,
        )

    def test_customer_portal_redirects_authenticated_non_customer(self):
        self.client.force_login(self.general_user)
        response = self.client.get(reverse("accounts:customer_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:home"))

    def test_customer_portal_redirects_anonymous_to_login(self):
        response = self.client.get(reverse("accounts:customer_dashboard"))
        expected = f"{reverse('accounts:login')}?{urlencode({'next': reverse('accounts:customer_dashboard')})}"
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], expected)

    def test_customer_portal_allows_customer_account(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse("accounts:customer_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_supplier_portal_redirects_authenticated_non_supplier(self):
        self.client.force_login(self.general_user)
        response = self.client.get(reverse("accounts:supplier_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("accounts:home"))

    def test_supplier_portal_redirects_anonymous_to_login(self):
        response = self.client.get(reverse("accounts:supplier_dashboard"))
        expected = f"{reverse('accounts:login')}?{urlencode({'next': reverse('accounts:supplier_dashboard')})}"
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], expected)

    def test_supplier_portal_allows_supplier_account(self):
        self.client.force_login(self.supplier_user)
        response = self.client.get(reverse("accounts:supplier_dashboard"))
        self.assertEqual(response.status_code, 200)


class MaintenanceReminderCommandTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="maintenance-owner",
            email="owner@example.com",
            password="testpass",
            first_name="Riley",
            last_name="Shaw",
        )
        self.profile = Profile.objects.create(
            user=self.owner,
            occupation="truck_mechanic",
            company_name="Roadside Mechanics",
            company_email="service@example.com",
        )
        self.customer = Customer.objects.create(
            user=self.owner,
            name="Fleet Logistics",
            email="fleet@example.com",
        )
        self.vehicle = Vehicle.objects.create(
            customer=self.customer,
            vin_number="1HGBH41JXMN109186",
            unit_number="A1",
            make_model="Freightliner Cascadia",
        )
        self.task = VehicleMaintenanceTask.objects.create(
            vehicle=self.vehicle,
            user=self.owner,
            title="Oil and filter change",
            due_date=timezone.localdate() + timedelta(days=3),
            priority=VehicleMaintenanceTask.PRIORITY_HIGH,
        )

    @override_settings(SITE_URL="https://portal.example.com", DEFAULT_FROM_EMAIL="noreply@example.com")
    def test_command_sends_email_and_marks_tasks(self):
        call_command("send_maintenance_reminders", days=7)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["fleet@example.com"])
        self.assertIn("Oil and filter change", message.body)
        self.assertIn("Freightliner Cascadia", message.body)

        self.task.refresh_from_db()
        self.assertIsNotNone(self.task.last_reminder_sent)

    def test_command_skips_recently_notified_tasks(self):
        self.task.last_reminder_sent = timezone.now()
        self.task.save(update_fields=["last_reminder_sent"])

        call_command("send_maintenance_reminders", days=7)

        self.assertEqual(len(mail.outbox), 0)


class InventoryLookupAndReorderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="parts-user", password="pass1234")
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(user=self.user, name="Fleet Parts Supply")

    def test_product_rejects_max_stock_below_reorder(self):
        product = Product(
            user=self.user,
            name="Air Dryer Cartridge",
            sku="ADC-100",
            cost_price=Decimal("20.00"),
            sale_price=Decimal("35.00"),
            reorder_level=5,
            max_stock_level=3,
        )
        with self.assertRaises(ValidationError) as exc:
            product.full_clean()

        self.assertIn(
            "Max stock level must be greater than or equal to reorder level.",
            exc.exception.messages,
        )

    def test_inventory_search_matches_barcode_and_oem(self):
        product = Product.objects.create(
            user=self.user,
            name="Brake Drum",
            sku="BD-200",
            oem_part_number="OEM-7788",
            barcode_value="0123456789012",
            cost_price=Decimal("70.00"),
            sale_price=Decimal("95.00"),
        )

        response = self.client.get(reverse("accounts:inventory_search"), {"q": "0123456789012"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        ids = [item["id"] for item in payload.get("results", [])]
        self.assertIn(product.id, ids)

        response = self.client.get(reverse("accounts:inventory_search"), {"q": "OEM-7788"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        ids = [item["id"] for item in payload.get("results", [])]
        self.assertIn(product.id, ids)

    def test_stock_orders_recommend_qty_to_max_stock(self):
        Product.objects.create(
            user=self.user,
            name="Drive Belt",
            sku="DB-500",
            supplier=self.supplier,
            cost_price=Decimal("12.00"),
            sale_price=Decimal("20.00"),
            quantity_in_stock=2,
            reorder_level=5,
            max_stock_level=12,
        )

        response = self.client.get(reverse("accounts:inventory_stock_orders"))
        self.assertEqual(response.status_code, 200)
        supplier_groups = response.context["supplier_groups"]
        self.assertEqual(len(supplier_groups), 1)

        first_item = supplier_groups[0]["products"][0]
        self.assertEqual(first_item["order_qty"], 10)
        self.assertEqual(first_item["max_stock_level"], 12)
        self.assertIn("Max: 12", supplier_groups[0]["email_body"])
