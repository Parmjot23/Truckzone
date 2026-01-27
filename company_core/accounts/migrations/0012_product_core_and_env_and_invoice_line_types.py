from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_groupedinvoice_online_orders'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='core_price',
            field=models.DecimalField(
                default=Decimal('0.00'),
                decimal_places=2,
                max_digits=10,
                null=True,
                blank=True,
                help_text='Core charge applied per unit (refundable when core is returned).',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='environmental_fee',
            field=models.DecimalField(
                default=Decimal('0.00'),
                decimal_places=2,
                max_digits=10,
                null=True,
                blank=True,
                help_text='Environmental fee applied per unit when applicable.',
            ),
        ),
        migrations.AddField(
            model_name='incomerecord2',
            name='parent_line',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='fee_lines',
                to='accounts.incomerecord2',
            ),
        ),
        migrations.AddField(
            model_name='incomerecord2',
            name='line_type',
            field=models.CharField(
                choices=[
                    ('product', 'Product'),
                    ('core_charge', 'Core charge'),
                    ('environment_fee', 'Environmental fee'),
                    ('custom', 'Custom'),
                ],
                default='custom',
                max_length=20,
            ),
        ),
    ]
