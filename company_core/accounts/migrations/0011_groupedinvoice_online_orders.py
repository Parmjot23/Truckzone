from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_product_stock'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupedinvoice',
            name='is_online_order',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='groupedinvoice',
            name='online_order_status',
            field=models.CharField(
                blank=True,
                choices=[('new', 'New'), ('ready', 'Ready'), ('picked', 'Picked')],
                db_index=True,
                max_length=20,
                null=True,
            ),
        ),
    ]
