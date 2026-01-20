import os
from zipfile import ZipFile

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand

# ────────────────────────────────────────────────────────────
# ⚠️  TEMPORARY hard-coded password.
#    Replace the text between the quotes with your Gmail app password.
#    Delete it the moment you have a proper env-var or .env in place.
# ────────────────────────────────────────────────────────────
HARDCODED_PASSWORD = "bdcy saat qavq fcus"
# ────────────────────────────────────────────────────────────


class Command(BaseCommand):
    help = (
        "Export data for all models in the accounts app "
        "(excluding MechExpense and MechExpenseItem) and email it"
    )

    def handle(self, *args, **kwargs):
        # Pick whichever password is available
        smtp_password = settings.EMAIL_HOST_PASSWORD or HARDCODED_PASSWORD
        if not smtp_password:
            self.stderr.write(self.style.ERROR(
                "No SMTP password available (neither settings nor HARDCODED_PASSWORD)."
            ))
            return

        export_dir = "exports"
        os.makedirs(export_dir, exist_ok=True)

        file_paths = []
        for model in apps.get_app_config("accounts").get_models():
            name = model.__name__
            if name in ("MechExpense", "MechExpenseItem"):
                self.stdout.write(self.style.WARNING(f"Skipping model {name}"))
                continue

            path = os.path.join(export_dir, f"{name.lower()}.json")
            with open(path, "w") as fp:
                fp.write(serializers.serialize("json", model.objects.all()))
            file_paths.append(path)
            self.stdout.write(self.style.SUCCESS(f"Exported {name} → {path}"))

        # Zip everything
        zip_path = os.path.join(export_dir, "accounts_data.zip")
        with ZipFile(zip_path, "w") as zipf:
            for p in file_paths:
                zipf.write(p, os.path.basename(p))

        # Build SMTP connection with fallback password
        connection = get_connection(
            backend=settings.EMAIL_BACKEND,
            host=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=settings.EMAIL_HOST_USER,
            password=smtp_password,
            use_tls=getattr(settings, "EMAIL_USE_TLS", False),
            use_ssl=getattr(settings, "EMAIL_USE_SSL", False),
        )

        # Send email
        email = EmailMessage(
            subject="Exported Accounts Data",
            body=(
                "Attached: exported data for all models in the accounts app "
                "(MechExpense and MechExpenseItem excluded)."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.SUPPORT_EMAIL],
            connection=connection,
        )
        email.attach_file(zip_path)
        try:
            email.send(fail_silently=False)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Failed to send email: {exc}"))
            return

        # Cleanup
        for p in file_paths:
            os.remove(p)
        os.remove(zip_path)

        self.stdout.write(self.style.SUCCESS(
            f"Email sent to {settings.SUPPORT_EMAIL}; exports cleaned up."
        ))
