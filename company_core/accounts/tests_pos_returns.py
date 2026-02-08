import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer,
    CustomerCredit,
    GroupedInvoice,
    IncomeRecord2,
    INVOICE_LINE_TYPE_CORE,
    INVOICE_LINE_TYPE_ENV,
    INVOICE_LINE_TYPE_PRODUCT,
    Product,
    Profile,
)


class PartsStorePosReturnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='parts_owner',
            email='owner@example.com',
            password='pass1234',
        )
        profile, _ = Profile.objects.get_or_create(
            user=self.user,
            defaults={'occupation': 'parts_store'},
        )
        profile.occupation = 'parts_store'
        profile.province = 'ON'
        profile.save(update_fields=['occupation', 'province'])

        self.client.force_login(self.user)

        self.customer = Customer.objects.create(
            user=self.user,
            name='Fleet Customer',
            email='fleet@example.com',
            address='123 Fleet Street',
        )
        self.product = Product.objects.create(
            user=self.user,
            name='Starter Motor',
            sku='STM-100',
            cost_price=Decimal('25.00'),
            sale_price=Decimal('45.00'),
            core_price=Decimal('12.00'),
            environmental_fee=Decimal('3.50'),
        )
        self.invoice = GroupedInvoice.objects.create(
            user=self.user,
            customer=self.customer,
            date=timezone.localdate(),
            bill_to=self.customer.name,
            bill_to_email=self.customer.email,
        )
        self.product_line = IncomeRecord2.objects.create(
            grouped_invoice=self.invoice,
            product=self.product,
            line_type=INVOICE_LINE_TYPE_PRODUCT,
            job='Starter Motor',
            qty=Decimal('2.00'),
            rate=Decimal('45.00'),
            date=timezone.localdate(),
        )
        self.core_line = IncomeRecord2.objects.create(
            grouped_invoice=self.invoice,
            parent_line=self.product_line,
            line_type=INVOICE_LINE_TYPE_CORE,
            job='Core charge - Starter Motor',
            qty=Decimal('2.00'),
            rate=Decimal('12.00'),
            date=timezone.localdate(),
        )
        self.env_line = IncomeRecord2.objects.create(
            grouped_invoice=self.invoice,
            parent_line=self.product_line,
            line_type=INVOICE_LINE_TYPE_ENV,
            job='Environmental fee - Starter Motor',
            qty=Decimal('2.00'),
            rate=Decimal('3.50'),
            date=timezone.localdate(),
        )

    def _lookup(self, return_type):
        return self.client.get(
            reverse('accounts:parts_store_return_lookup'),
            {'customer_id': self.customer.id, 'return_type': return_type},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def _create_return(self, return_type, line_items):
        return self.client.post(
            reverse('accounts:parts_store_return_create'),
            {
                'customer_id': str(self.customer.id),
                'return_type': return_type,
                'date': timezone.localdate().isoformat(),
                'line_items': json.dumps(line_items),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_lookup_filters_core_vs_product_lines(self):
        core_resp = self._lookup('core')
        self.assertEqual(core_resp.status_code, 200)
        core_data = core_resp.json()
        self.assertTrue(core_data.get('success'))
        core_ids = [
            item['source_invoice_item_id']
            for invoice in core_data.get('invoices', [])
            for item in invoice.get('items', [])
        ]
        self.assertEqual(core_ids, [self.core_line.id])

        product_resp = self._lookup('product')
        self.assertEqual(product_resp.status_code, 200)
        product_data = product_resp.json()
        self.assertTrue(product_data.get('success'))
        product_ids = [
            item['source_invoice_item_id']
            for invoice in product_data.get('invoices', [])
            for item in invoice.get('items', [])
        ]
        self.assertEqual(product_ids, [self.product_line.id])

    def test_create_product_return_creates_customer_credit(self):
        resp = self._create_return(
            'product',
            [{'source_invoice_item_id': self.product_line.id, 'qty': '1'}],
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get('success'))

        credit = CustomerCredit.objects.get(pk=payload['credit_id'])
        self.assertTrue(credit.record_in_inventory)
        item = credit.items.get()
        self.assertEqual(item.source_invoice_item_id, self.product_line.id)
        self.assertEqual(Decimal(str(item.qty)), Decimal('1'))

    def test_core_return_rejects_wrong_line_type_and_over_return(self):
        wrong_line_resp = self._create_return(
            'core',
            [{'source_invoice_item_id': self.product_line.id, 'qty': '1'}],
        )
        self.assertEqual(wrong_line_resp.status_code, 400)
        self.assertFalse(wrong_line_resp.json().get('success'))

        first_core_resp = self._create_return(
            'core',
            [{'source_invoice_item_id': self.core_line.id, 'qty': '1'}],
        )
        self.assertEqual(first_core_resp.status_code, 200)
        first_payload = first_core_resp.json()
        credit = CustomerCredit.objects.get(pk=first_payload['credit_id'])
        self.assertFalse(credit.record_in_inventory)

        over_return_resp = self._create_return(
            'core',
            [{'source_invoice_item_id': self.core_line.id, 'qty': '2'}],
        )
        self.assertEqual(over_return_resp.status_code, 400)
        self.assertIn('Only', over_return_resp.json().get('error', ''))

    def test_core_return_requires_positive_product_core_price(self):
        self.product.core_price = Decimal('0.00')
        self.product.save(update_fields=['core_price'])

        core_lookup_resp = self._lookup('core')
        self.assertEqual(core_lookup_resp.status_code, 200)
        core_data = core_lookup_resp.json()
        self.assertTrue(core_data.get('success'))
        core_ids = [
            item['source_invoice_item_id']
            for invoice in core_data.get('invoices', [])
            for item in invoice.get('items', [])
        ]
        self.assertEqual(core_ids, [])

        core_create_resp = self._create_return(
            'core',
            [{'source_invoice_item_id': self.core_line.id, 'qty': '1'}],
        )
        self.assertEqual(core_create_resp.status_code, 400)
        self.assertIn('no core charge configured', core_create_resp.json().get('error', '').lower())

    def test_env_return_type_is_not_supported(self):
        env_lookup_resp = self._lookup('env')
        self.assertEqual(env_lookup_resp.status_code, 400)
        self.assertIn('choose return type', env_lookup_resp.json().get('error', '').lower())

        env_create_resp = self._create_return(
            'env',
            [{'source_invoice_item_id': self.env_line.id, 'qty': '1'}],
        )
        self.assertEqual(env_create_resp.status_code, 400)
        self.assertIn('choose return type', env_create_resp.json().get('error', '').lower())
