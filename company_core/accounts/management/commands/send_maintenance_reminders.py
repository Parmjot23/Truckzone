import collections
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from accounts.models import VehicleMaintenanceTask
from accounts.pdf_utils import apply_branding_defaults
from accounts.utils import build_cc_list


class Command(BaseCommand):
    help = "Send maintenance due reminder emails to customers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Number of days ahead to look for upcoming maintenance tasks (default: 7).",
        )

    def handle(self, *args, **options):
        days_ahead = options["days"]
        today = timezone.localdate()
        window_end = today + timedelta(days=days_ahead)
        now = timezone.now()

        tasks = (
            VehicleMaintenanceTask.objects.select_related(
                "vehicle__customer",
                "vehicle__customer__portal_user",
                "user__profile",
            )
            .filter(status__in=VehicleMaintenanceTask.active_statuses())
            .filter(due_date__isnull=False, due_date__lte=window_end)
            .filter(
                Q(last_reminder_sent__isnull=True)
                | Q(last_reminder_sent__lt=now - timedelta(days=1))
            )
        )

        if not tasks.exists():
            self.stdout.write(self.style.SUCCESS("No maintenance reminders to send."))
            return

        tasks_by_customer = collections.defaultdict(list)
        customer_cache = {}
        for task in tasks:
            customer = getattr(task.vehicle, "customer", None)
            if customer is None:
                continue
            tasks_by_customer[customer.pk].append(task)
            customer_cache[customer.pk] = customer

        reminders_sent = 0
        for customer_id, customer_tasks in tasks_by_customer.items():
            customer = customer_cache.get(customer_id)
            if customer is None:
                continue
            recipient = (customer.email or None)
            if not recipient and getattr(customer, "portal_user", None):
                recipient = customer.portal_user.email or None

            if not recipient:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping customer {customer.name} (ID {customer.id}) - no email on file."
                    )
                )
                continue
            customer_cc_emails = customer.get_cc_emails()
            cc_recipients = build_cc_list(*customer_cc_emails, exclude=[recipient])

            business_user = customer.user
            profile = getattr(business_user, "profile", None)
            business_name = (
                (profile.company_name if profile and profile.company_name else None)
                or business_user.get_full_name()
                or business_user.username
            )
            contact_email = (
                (profile.company_email if profile and profile.company_email else None)
                or business_user.email
                or settings.DEFAULT_FROM_EMAIL
            )

            portal_url = None
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            if site_url:
                portal_url = f"{site_url}{reverse('accounts:customer_dashboard')}"

            overdue_tasks = []
            upcoming_tasks = []
            for task in sorted(
                customer_tasks,
                key=lambda t: (
                    t.due_date or window_end,
                    t.priority,
                    t.title.lower(),
                ),
            ):
                if task.due_date and task.due_date < today:
                    overdue_tasks.append(task)
                else:
                    upcoming_tasks.append(task)

            context = {
                "customer": customer,
                "profile": profile,
                "business_name": business_name,
                "contact_email": contact_email,
                "overdue_tasks": overdue_tasks,
                "upcoming_tasks": upcoming_tasks,
                "today": today,
                "window_end": window_end,
                "portal_url": portal_url,
                "days_ahead": days_ahead,
            }
            context = apply_branding_defaults(context)

            subject = f"Upcoming maintenance reminders from {business_name}"
            html_body = render_to_string("emails/maintenance_due_email.html", context)
            text_body = strip_tags(html_body)

            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
                cc=cc_recipients or None,
            )
            email.attach_alternative(html_body, "text/html")

            try:
                email.send()
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed to send maintenance reminder to {recipient} for customer {customer.name}: {exc}"
                    )
                )
                continue

            task_ids = [task.id for task in customer_tasks]
            VehicleMaintenanceTask.objects.filter(id__in=task_ids).update(
                last_reminder_sent=now
            )

            reminders_sent += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sent maintenance reminder to {recipient} for customer {customer.name}."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"Completed maintenance reminder run for {reminders_sent} customer(s).")
        )
