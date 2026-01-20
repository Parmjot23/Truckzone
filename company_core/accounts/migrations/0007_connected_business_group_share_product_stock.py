from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_connected_business_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectedbusinessgroup",
            name="share_product_stock",
            field=models.BooleanField(
                default=True,
                help_text="Share stock on hand across connected businesses.",
            ),
        ),
    ]
