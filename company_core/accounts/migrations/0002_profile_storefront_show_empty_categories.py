from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='storefront_show_empty_categories',
            field=models.BooleanField(
                default=True,
                help_text='Show category groups and categories even when no products are published.',
            ),
        ),
    ]
