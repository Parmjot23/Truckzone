from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_storefront_suggestions'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='ui_font_family',
            field=models.CharField(
                choices=[
                    ('manrope', 'Modern Sans (Manrope + Sora)'),
                    ('inter', 'Clean UI (Inter + Space Grotesk)'),
                    ('poppins', 'Classic Readable (Poppins + Merriweather)'),
                    ('system', 'System Default'),
                ],
                default='manrope',
                help_text='Controls the font family for portal and dashboard pages.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='ui_font_public_family',
            field=models.CharField(
                choices=[
                    ('manrope', 'Modern Sans (Manrope + Sora)'),
                    ('inter', 'Clean UI (Inter + Space Grotesk)'),
                    ('poppins', 'Classic Readable (Poppins + Merriweather)'),
                    ('system', 'System Default'),
                ],
                default='manrope',
                help_text='Controls the font family for public website pages.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='ui_font_public_size_percentage',
            field=models.PositiveIntegerField(
                choices=[
                    (80, 'Small (80%)'),
                    (90, 'Comfortable Small (90%)'),
                    (100, 'Default (100%)'),
                    (110, 'Large (110%)'),
                    (120, 'Extra Large (120%)'),
                    (130, 'Maximum (130%)'),
                ],
                default=100,
                help_text='Controls base text size for public website pages.',
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='ui_font_public_weight',
            field=models.PositiveIntegerField(
                choices=[
                    (400, 'Regular (400)'),
                    (500, 'Medium (500)'),
                    (600, 'Semi Bold (600)'),
                    (700, 'Bold (700)'),
                ],
                default=500,
                help_text='Controls base text weight for public website pages.',
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='ui_font_size_percentage',
            field=models.PositiveIntegerField(
                choices=[
                    (80, 'Small (80%)'),
                    (90, 'Comfortable Small (90%)'),
                    (100, 'Default (100%)'),
                    (110, 'Large (110%)'),
                    (120, 'Extra Large (120%)'),
                    (130, 'Maximum (130%)'),
                ],
                default=100,
                help_text='Controls base text size for portal and dashboard pages.',
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='ui_font_weight',
            field=models.PositiveIntegerField(
                choices=[
                    (400, 'Regular (400)'),
                    (500, 'Medium (500)'),
                    (600, 'Semi Bold (600)'),
                    (700, 'Bold (700)'),
                ],
                default=500,
                help_text='Controls base text weight for portal and dashboard pages.',
            ),
        ),
    ]
