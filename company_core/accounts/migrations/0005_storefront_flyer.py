from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_profile_storefront_is_visible'),
    ]

    operations = [
        migrations.CreateModel(
            name='StorefrontFlyer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=False)),
                ('title', models.CharField(blank=True, max_length=120)),
                ('subtitle', models.CharField(blank=True, max_length=200)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='storefront_flyer', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Storefront flyer',
                'verbose_name_plural': 'Storefront flyers',
            },
        ),
    ]
