from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

DEFAULT_USERNAMES = ",".join(
    name
    for name in [
        (getattr(settings, "DEFAULT_BUSINESS_EMAIL", "") or "").strip(),
        "parminder",
    ]
    if name
)


class Command(BaseCommand):
    help = "Set (or reset) passwords for specific usernames. Creates the user if missing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--usernames",
            type=str,
            default=DEFAULT_USERNAMES or "parminder",
            help="Comma-separated list of usernames to update/create.",
        )
        parser.add_argument(
            "--password",
            type=str,
            required=True,
            help="Password to set for all listed users.",
        )
        parser.add_argument(
            "--no-create",
            action="store_true",
            help="Do not create users that are missing; error instead.",
        )

    def handle(self, *args, **options):
        usernames = [
            name.strip() for name in options["usernames"].split(",") if name.strip()
        ]
        if not usernames:
            raise CommandError("No usernames provided.")

        password = options["password"]
        allow_create = not options["no_create"]
        User = get_user_model()

        for username in usernames:
            try:
                user = User.objects.get(username=username)
                created = False
            except User.DoesNotExist:
                if not allow_create:
                    raise CommandError(
                        f"User '{username}' does not exist and --no-create was set."
                    )
                user = User.objects.create_user(username=username)
                created = True

            user.set_password(password)
            user.save(update_fields=["password"])

            action = "created" if created else "updated"
            self.stdout.write(self.style.SUCCESS(f"{action.capitalize()} password for {username}"))

        self.stdout.write(self.style.SUCCESS("Password updates complete."))
