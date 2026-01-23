from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_storefront_cart_item'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerCredit',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('customer_name', models.CharField(blank=True, max_length=150)),
                ('credit_no', models.CharField(blank=True, max_length=20, null=True, unique=True)),
                ('date', models.DateField(null=True)),
                ('memo', models.TextField(blank=True, null=True)),
                ('tax_included', models.BooleanField(default=False)),
                ('province', models.CharField(blank=True, choices=[('AB', 'Alberta'), ('BC', 'British Columbia'), ('MB', 'Manitoba'), ('NB', 'New Brunswick'), ('NL', 'Newfoundland and Labrador'), ('NT', 'Northwest Territories'), ('NS', 'Nova Scotia'), ('NU', 'Nunavut'), ('ON', 'Ontario'), ('PE', 'Prince Edward Island'), ('QC', 'Quebec'), ('SK', 'Saskatchewan'), ('YT', 'Yukon'), ('CU', 'Custom')], max_length=2, null=True)),
                ('custom_tax_rate', models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True)),
                ('record_in_inventory', models.BooleanField(default=True, help_text='When enabled, credit items adjust inventory stock levels.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='credits', to='accounts.customer')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='auth.user')),
            ],
        ),
        migrations.CreateModel(
            name='CustomerCreditItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('part_no', models.CharField(blank=True, max_length=50, null=True)),
                ('description', models.TextField(blank=True, null=True)),
                ('qty', models.FloatField(default=1)),
                ('price', models.FloatField(default=0)),
                ('amount', models.FloatField(default=0, editable=False)),
                ('tax_paid', models.FloatField(default=0, editable=False)),
                ('customer_credit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='accounts.customercredit')),
                ('product', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='customer_credit_items', to='accounts.product')),
                ('source_invoice', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='customer_credit_items', to='accounts.groupedinvoice')),
                ('source_invoice_item', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='customer_credit_items', to='accounts.incomerecord2')),
            ],
            options={
                'verbose_name': 'Customer Credit Item',
                'verbose_name_plural': 'Customer Credit Items',
            },
        ),
    ]
