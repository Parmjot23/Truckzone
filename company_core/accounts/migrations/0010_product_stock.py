from django.db import migrations, models
import django.db.models.deletion


def seed_product_stock(apps, schema_editor):
    Product = apps.get_model("accounts", "Product")
    ProductStock = apps.get_model("accounts", "ProductStock")
    db_alias = schema_editor.connection.alias
    batch = []
    batch_size = 1000

    for product in Product.objects.using(db_alias).all().iterator():
        batch.append(
            ProductStock(
                product_id=product.id,
                user_id=product.user_id,
                quantity_in_stock=product.quantity_in_stock or 0,
                reorder_level=product.reorder_level or 0,
            )
        )
        if len(batch) >= batch_size:
            ProductStock.objects.using(db_alias).bulk_create(batch, ignore_conflicts=True)
            batch = []

    if batch:
        ProductStock.objects.using(db_alias).bulk_create(batch, ignore_conflicts=True)


def reverse_seed_product_stock(apps, schema_editor):
    ProductStock = apps.get_model("accounts", "ProductStock")
    db_alias = schema_editor.connection.alias
    ProductStock.objects.using(db_alias).all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_customer_credit"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductStock",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity_in_stock", models.PositiveIntegerField(default=0)),
                ("reorder_level", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "product",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stock_levels", to="accounts.product"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="product_stocks", to="auth.user"),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("product", "user"), name="unique_product_stock_per_user"),
                ],
            },
        ),
        migrations.RunPython(seed_product_stock, reverse_seed_product_stock),
    ]
