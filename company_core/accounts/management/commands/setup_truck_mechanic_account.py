import secrets
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Profile, QuickBooksSettings
from accounts.quickbooks_desktop_service import QuickBooksDesktopService
from accounts.quickbooks_service import QuickBooksService


class Command(BaseCommand):
    help = (
        "Create (or update) a dedicated Truck Mechanic business account and import QuickBooks data into it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="truck_mechanic",
            help="Username for the new Truck Mechanic account.",
        )
        parser.add_argument(
            "--email",
            default="",
            help="Email for the account (optional).",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Password for the account (optional). If omitted, a random password is generated.",
        )
        parser.add_argument(
            "--company-name",
            default="Truck Mechanic",
            help="Company name stored on the profile.",
        )

        parser.add_argument(
            "--integration-type",
            choices=[QuickBooksSettings.INTEGRATION_ONLINE, QuickBooksSettings.INTEGRATION_DESKTOP],
            default=QuickBooksSettings.INTEGRATION_ONLINE,
            help="QuickBooks integration type to configure for this account.",
        )
        parser.add_argument(
            "--environment",
            choices=[QuickBooksSettings.ENVIRONMENT_SANDBOX, QuickBooksSettings.ENVIRONMENT_PRODUCTION],
            default=QuickBooksSettings.ENVIRONMENT_PRODUCTION,
            help="QuickBooks Online environment (ignored for Desktop).",
        )
        parser.add_argument("--client-id", default="", help="QuickBooks Online client_id (Online only).")
        parser.add_argument("--client-secret", default="", help="QuickBooks Online client_secret (Online only).")
        parser.add_argument("--realm-id", default="", help="QuickBooks Online realm/company id (Online only).")
        parser.add_argument("--refresh-token", default="", help="QuickBooks Online refresh token (Online only).")
        parser.add_argument(
            "--redirect-uri",
            default="",
            help="OAuth redirect URI (optional; Online only).",
        )
        parser.add_argument(
            "--desktop-company-name",
            default="",
            help="Company name exactly as it appears in QuickBooks Desktop (Desktop only).",
        )
        parser.add_argument(
            "--desktop-iif",
            default="",
            help="Path to a QuickBooks Desktop IIF export to import (Desktop only).",
        )

        parser.add_argument(
            "--import",
            dest="do_import",
            action="store_true",
            help="Actually import data after configuring the account.",
        )
        parser.add_argument("--import-all", action="store_true", help="Import customers, items, and invoices.")
        parser.add_argument("--import-customers", action="store_true", help="Import customers (Online only).")
        parser.add_argument("--import-items", action="store_true", help="Import items/products (Online only).")
        parser.add_argument("--import-invoices", action="store_true", help="Import invoices.")

        parser.add_argument(
            "--since-days",
            type=int,
            default=None,
            help="Import invoices updated within the last N days (Online only).",
        )
        parser.add_argument(
            "--since",
            default=None,
            help="Import invoices updated since an ISO datetime (Online only). Example: 2025-01-01T00:00:00Z",
        )

    def handle(self, *args, **options):
        username = (options.get("username") or "").strip()
        email = (options.get("email") or "").strip()
        password = options.get("password")
        company_name = (options.get("company_name") or "Truck Mechanic").strip()
        integration_type = options["integration_type"]

        if not username:
            raise CommandError("--username is required")

        user = User.objects.filter(username__iexact=username).first()
        created_user = False
        if not user:
            if password is None:
                password = secrets.token_urlsafe(12)
            user = User.objects.create_user(username=username, email=email or None, password=password)
            created_user = True
        else:
            if email and (user.email or "") != email:
                user.email = email
                user.save(update_fields=["email"])
            if password:
                user.set_password(password)
                user.save(update_fields=["password"])

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])

        profile, created_profile = Profile.objects.get_or_create(
            user=user,
            defaults={
                "occupation": "truck_mechanic",
                "company_name": company_name,
                "company_email": email or None,
                "business_owner": user,
                "is_business_admin": True,
                "admin_approved": True,
            },
        )
        changed_profile_fields = []
        if profile.occupation != "truck_mechanic":
            profile.occupation = "truck_mechanic"
            changed_profile_fields.append("occupation")
        if company_name and (profile.company_name or "") != company_name:
            profile.company_name = company_name
            changed_profile_fields.append("company_name")
        if email and (profile.company_email or "") != email:
            profile.company_email = email
            changed_profile_fields.append("company_email")
        if profile.business_owner_id != user.id:
            profile.business_owner = user
            changed_profile_fields.append("business_owner")
        if not profile.is_business_admin:
            profile.is_business_admin = True
            changed_profile_fields.append("is_business_admin")
        if not profile.admin_approved:
            profile.admin_approved = True
            changed_profile_fields.append("admin_approved")
        if changed_profile_fields:
            profile.save(update_fields=changed_profile_fields)

        qb_defaults = {
            "integration_type": integration_type,
        }

        if integration_type == QuickBooksSettings.INTEGRATION_DESKTOP:
            desktop_company = (options.get("desktop_company_name") or "").strip()
            if not desktop_company:
                raise CommandError("--desktop-company-name is required for Desktop integration.")
            qb_defaults.update(
                {
                    "desktop_company_name": desktop_company,
                    "environment": options["environment"],  # harmless, but not used for desktop
                    "client_id": "",
                    "client_secret": "",
                    "realm_id": "",
                    "refresh_token": None,
                    "redirect_uri": "",
                }
            )
        else:
            client_id = (options.get("client_id") or "").strip()
            client_secret = (options.get("client_secret") or "").strip()
            realm_id = (options.get("realm_id") or "").strip()
            refresh_token = (options.get("refresh_token") or "").strip()
            redirect_uri = (options.get("redirect_uri") or "").strip()

            missing = [k for k, v in [("client-id", client_id), ("client-secret", client_secret), ("realm-id", realm_id), ("refresh-token", refresh_token)] if not v]
            if missing:
                raise CommandError(
                    "Missing required QuickBooks Online fields: "
                    + ", ".join(f"--{name}" for name in missing)
                )
            qb_defaults.update(
                {
                    "environment": options["environment"],
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "realm_id": realm_id,
                    "refresh_token": refresh_token,
                    "redirect_uri": redirect_uri,
                }
            )

        qb_settings, qb_created = QuickBooksSettings.objects.update_or_create(
            user=user,
            defaults=qb_defaults,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Truck Mechanic account ready: username={user.username} (created={created_user}), "
                f"profile(created={created_profile}), quickbooks_settings(created={qb_created})"
            )
        )
        if created_user and password:
            self.stdout.write(self.style.WARNING(f"Generated password for {user.username}: {password}"))

        if not options.get("do_import"):
            return

        import_all = options.get("import_all")
        import_customers = options.get("import_customers") or False
        import_items = options.get("import_items") or False
        import_invoices = options.get("import_invoices") or False
        if not any([import_all, import_customers, import_items, import_invoices]):
            import_all = True

        if qb_settings.integration_type == QuickBooksSettings.INTEGRATION_DESKTOP:
            iif_path = (options.get("desktop_iif") or "").strip()
            if not iif_path:
                raise CommandError("--desktop-iif is required to import QuickBooks Desktop data.")
            try:
                with open(iif_path, "r", encoding="utf-8-sig") as fp:
                    payload = fp.read()
            except OSError as exc:
                raise CommandError(f"Unable to read IIF file: {iif_path} ({exc})") from exc

            created, updated = QuickBooksDesktopService(qb_settings).import_invoices(
                user=user,
                file_contents=payload,
                source_name=iif_path,
            )
            self.stdout.write(self.style.SUCCESS(f"Desktop import complete: invoices created={created}, updated={updated}"))
            return

        # Online import
        service = QuickBooksService(qb_settings)
        service.ensure_access_token()

        since = None
        if options.get("since"):
            try:
                raw = str(options["since"]).replace("Z", "+00:00")
                since = datetime.fromisoformat(raw)
                if timezone.is_naive(since):
                    since = timezone.make_aware(since, timezone=timezone.utc)
            except Exception as exc:
                raise CommandError(f"Invalid --since value (must be ISO datetime): {options['since']}") from exc
        elif options.get("since_days") is not None:
            since = timezone.now() - timedelta(days=int(options["since_days"]))

        if import_all or import_customers:
            c_created, c_updated = service.import_customers(user=user)
            self.stdout.write(self.style.SUCCESS(f"Imported customers: created={c_created}, updated={c_updated}"))

        if import_all or import_items:
            p_created, p_updated = service.import_items(user=user)
            self.stdout.write(self.style.SUCCESS(f"Imported items: created={p_created}, updated={p_updated}"))

        if import_all or import_invoices:
            i_created, i_updated = service.import_invoices(user=user, since=since)
            self.stdout.write(self.style.SUCCESS(f"Imported invoices: created={i_created}, updated={i_updated}"))

