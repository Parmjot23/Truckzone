from django.db import migrations, models


MEDIA_NAME_PREFIXES = (
    "/workspace/media/",
    "workspace/media/",
    "/media/",
    "media/",
)


def _normalize_media_name(value):
    if not value:
        return value

    normalized = str(value).strip().replace("\\", "/")
    if "://" in normalized:
        return str(value).strip()

    while normalized.startswith("./"):
        normalized = normalized[2:]

    while True:
        lower_value = normalized.lower()
        removed_prefix = False
        for prefix in MEDIA_NAME_PREFIXES:
            if lower_value.startswith(prefix):
                normalized = normalized[len(prefix):].lstrip("/")
                removed_prefix = True
                break
        if not removed_prefix:
            break

    return normalized


def normalize_media_file_paths(apps, schema_editor):
    app_config = apps.get_app_config("accounts")

    for model in app_config.get_models():
        file_field_names = [
            field.name
            for field in model._meta.fields
            if isinstance(field, models.FileField)
        ]
        if not file_field_names:
            continue

        updates = []
        queryset = model.objects.all().only("pk", *file_field_names)
        for obj in queryset.iterator(chunk_size=500):
            changed = False
            for field_name in file_field_names:
                current_value = getattr(obj, field_name, None)
                current_name = getattr(current_value, "name", current_value)
                if not current_name:
                    continue

                normalized_name = _normalize_media_name(current_name)
                if normalized_name != current_name:
                    setattr(obj, field_name, normalized_name)
                    changed = True

            if changed:
                updates.append(obj)

            if len(updates) >= 500:
                model.objects.bulk_update(
                    updates,
                    file_field_names,
                    batch_size=500,
                )
                updates = []

        if updates:
            model.objects.bulk_update(
                updates,
                file_field_names,
                batch_size=500,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_profile_display_typography"),
    ]

    operations = [
        migrations.RunPython(
            normalize_media_file_paths,
            migrations.RunPython.noop,
        ),
    ]

