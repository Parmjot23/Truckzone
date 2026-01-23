#!/usr/bin/env python
"""
Set random on-hand stock (10-20) for all inventory products and
set reorder level to 2.
"""

import os
import random

import django


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blank_template.settings")
    django.setup()

    from accounts.models import InventoryTransaction, Product

    inventory_qs = Product.objects.filter(item_type="inventory")
    total_products = inventory_qs.count()
    if total_products == 0:
        print("No inventory products found.")
        return

    updated_reorder = inventory_qs.update(reorder_level=2)
    adjustments = 0

    for product in inventory_qs.iterator():
        new_qty = random.randint(10, 20)
        InventoryTransaction.objects.create(
            product=product,
            transaction_type="ADJUSTMENT",
            quantity=new_qty,
            remarks="Seed stock to random on-hand quantity",
            user=product.user,
        )
        adjustments += 1

    print(f"Updated reorder_level=2 for {updated_reorder} products.")
    print(f"Created {adjustments} stock adjustments.")


if __name__ == "__main__":
    main()
