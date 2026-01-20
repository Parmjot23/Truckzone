from __future__ import annotations

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    Employee,
    EmployeeRecurringDeduction,
    EmployeeTaxProfile,
    PayrollEmployerTax,
    PayrollRun,
    PayrollSettings,
    PayrollProvinceTaxSetting,
    PayrollTaxBracket,
    PayrollTaxYear,
    ShiftTemplate,
    TimeEntry,
    Timesheet,
)
from accounts.payroll_utils import get_pay_period_for_date
from accounts.payroll_views import _generate_paystubs_for_run
from accounts.utils import get_business_user, get_primary_business_user


class Command(BaseCommand):
    help = "Seed demo payroll data (employees, timesheets, time entries, payroll run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            help="Username to attach demo payroll data to.",
        )
        parser.add_argument(
            "--employees",
            type=int,
            default=6,
            help="Number of employees to ensure exist for the demo.",
        )
        parser.add_argument(
            "--periods",
            type=int,
            default=2,
            help="Number of pay periods to generate timesheets for.",
        )

    def handle(self, *args, **options):
        username = options.get("username")
        employee_target = max(int(options.get("employees") or 0), 0)
        period_count = max(int(options.get("periods") or 0), 1)

        UserModel = get_user_model()
        if username:
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist as exc:
                raise CommandError(f"User not found: {username}") from exc
        else:
            user = get_primary_business_user() or UserModel.objects.order_by("id").first()
            if not user:
                raise CommandError("No users exist. Create a user first.")

        business_user = get_business_user(user)
        settings_obj, created_settings = PayrollSettings.objects.get_or_create(user=business_user)
        if created_settings:
            settings_obj.overtime_enabled = True
            settings_obj.overtime_daily_enabled = True
            settings_obj.overtime_weekly_enabled = True
            settings_obj.save(
                update_fields=[
                    "overtime_enabled",
                    "overtime_daily_enabled",
                    "overtime_weekly_enabled",
                ]
            )

        shift_templates = [
            ("Day Shift 8-5", datetime.time(8, 0), datetime.time(17, 0)),
            ("Late Shift 9-6", datetime.time(9, 0), datetime.time(18, 0)),
            ("Split Shift 7-3", datetime.time(7, 0), datetime.time(15, 0)),
        ]
        for name, start_time, end_time in shift_templates:
            ShiftTemplate.objects.get_or_create(
                user=business_user,
                name=name,
                defaults={"start_time": start_time, "end_time": end_time, "active": True},
            )

        existing_employees = list(
            Employee.objects.filter(user=business_user).order_by("first_name", "last_name")
        )
        base_names = [
            ("Alex", "Hughes"),
            ("Jamie", "Patel"),
            ("Morgan", "Lee"),
            ("Taylor", "Singh"),
            ("Chris", "Martin"),
            ("Jordan", "Lopez"),
            ("Riley", "Walker"),
            ("Casey", "Kim"),
        ]
        provinces = [choice[0] for choice in EmployeeTaxProfile._meta.get_field("province").choices]

        created_employees = 0
        while len(existing_employees) < employee_target:
            idx = len(existing_employees)
            first_name, last_name = base_names[idx % len(base_names)]
            if idx >= len(base_names):
                last_name = f"{last_name}{idx + 1}"
            employee, created_emp = Employee.objects.get_or_create(
                user=business_user,
                first_name=first_name,
                last_name=last_name,
                defaults={
                    "email": f"{first_name.lower()}.{last_name.lower()}@example.com",
                    "role": Employee.ROLE_MECHANIC if idx % 2 == 0 else Employee.ROLE_OTHER,
                    "status": Employee.STATUS_ACTIVE,
                    "hourly_rate": Decimal("32.50") if idx % 2 == 0 else Decimal("28.00"),
                },
            )
            if created_emp:
                created_employees += 1
            existing_employees.append(employee)

        for idx, employee in enumerate(existing_employees[:employee_target]):
            EmployeeTaxProfile.objects.get_or_create(
                employee=employee,
                defaults={
                    "province": provinces[idx % len(provinces)],
                    "federal_claim_amount": Decimal("0.00"),
                    "provincial_claim_amount": Decimal("0.00"),
                },
            )

        if existing_employees:
            EmployeeRecurringDeduction.objects.get_or_create(
                employee=existing_employees[0],
                name="Union dues",
                defaults={"amount": Decimal("25.00"), "is_pre_tax": False},
            )
        if len(existing_employees) > 1:
            EmployeeRecurringDeduction.objects.get_or_create(
                employee=existing_employees[1],
                name="Health benefit",
                defaults={
                    "amount": Decimal("45.00"),
                    "is_pre_tax": True,
                    "is_employee_contribution": True,
                },
            )

        shift_days = {
            PayrollSettings.PAY_PERIOD_WEEKLY: 7,
            PayrollSettings.PAY_PERIOD_BIWEEKLY: 14,
            PayrollSettings.PAY_PERIOD_SEMIMONTHLY: 16,
            PayrollSettings.PAY_PERIOD_MONTHLY: 31,
        }.get(settings_obj.pay_period_frequency, 14)

        today = timezone.localdate()
        periods = []
        for idx in range(period_count):
            target_date = today - datetime.timedelta(days=idx * shift_days)
            start, end = get_pay_period_for_date(settings_obj, target_date)
            if (start, end) not in periods:
                periods.append((start, end))

        created_timesheets = 0
        created_entries = 0
        with transaction.atomic():
            for period_index, (period_start, period_end) in enumerate(periods):
                is_current_period = period_start <= today <= period_end
                for emp_index, employee in enumerate(existing_employees[:employee_target]):
                    status = Timesheet.STATUS_SUBMITTED if is_current_period else Timesheet.STATUS_APPROVED
                    timesheet, created_sheet = Timesheet.objects.get_or_create(
                        employee=employee,
                        period_start=period_start,
                        period_end=period_end,
                        defaults={
                            "created_by": user,
                            "status": status,
                            "notes": "Demo timesheet",
                            "approved_at": timezone.now() if status == Timesheet.STATUS_APPROVED else None,
                            "approved_by": user if status == Timesheet.STATUS_APPROVED else None,
                        },
                    )
                    if created_sheet:
                        created_timesheets += 1
                        work_dates = self._build_work_dates(period_start, period_end, limit=3 if is_current_period else 5)
                        for day_index, work_date in enumerate(work_dates):
                            start_time = datetime.time(9, 0)
                            end_time = datetime.time(17, 0)
                            if day_index == 2 and emp_index == 0 and not is_current_period:
                                end_time = datetime.time(19, 0)
                            TimeEntry.objects.create(
                                timesheet=timesheet,
                                work_date=work_date,
                                start_time=start_time,
                                end_time=end_time,
                                notes="Demo entry",
                            )
                            created_entries += 1

        run_created = False
        paystubs_generated = False
        latest_period = None
        if periods:
            past_periods = [period for period in periods if period[1] < today]
            latest_period = max(past_periods, key=lambda p: p[0]) if past_periods else periods[0]
            payroll_run, created_run = PayrollRun.objects.get_or_create(
                user=business_user,
                period_start=latest_period[0],
                period_end=latest_period[1],
                defaults={
                    "created_by": user,
                    "pay_date": latest_period[1]
                    + datetime.timedelta(days=settings_obj.default_pay_date_offset_days),
                },
            )
            run_created = created_run
            if payroll_run.status == PayrollRun.STATUS_DRAFT:
                payroll_run.status = PayrollRun.STATUS_APPROVED
                payroll_run.approved_at = timezone.now()
                payroll_run.approved_by = user
                payroll_run.save(update_fields=["status", "approved_at", "approved_by"])
            used_provinces = set(
                EmployeeTaxProfile.objects.filter(employee__in=existing_employees[:employee_target]).values_list(
                    "province", flat=True
                )
            )
            if not used_provinces:
                used_provinces = {"ON"}
            self._ensure_tax_configuration(latest_period[1], used_provinces)
            try:
                _generate_paystubs_for_run(payroll_run, settings_obj)
                paystubs_generated = True
            except ValueError as exc:
                paystubs_generated = False
                self.stdout.write(self.style.WARNING(f"Paystub generation skipped: {exc}"))

        self.stdout.write(self.style.SUCCESS("Payroll demo data seeded."))
        self.stdout.write(f"Business user: {business_user.username}")
        self.stdout.write(f"Employees created: {created_employees}")
        self.stdout.write(f"Timesheets created: {created_timesheets}")
        self.stdout.write(f"Time entries created: {created_entries}")
        self.stdout.write(f"Payroll run created: {run_created}")
        self.stdout.write(f"Paystubs generated: {paystubs_generated}")

    @staticmethod
    def _build_work_dates(period_start, period_end, *, limit=5):
        work_dates = []
        current = period_start
        while current <= period_end and len(work_dates) < limit:
            if current.weekday() < 5:
                work_dates.append(current)
            current += datetime.timedelta(days=1)
        return work_dates

    @staticmethod
    def _ensure_tax_configuration(target_date, provinces):
        tax_year, created_year = PayrollTaxYear.objects.get_or_create(
            year=target_date.year,
            defaults={
                "cpp_rate": Decimal("0.0595"),
                "cpp_basic_exemption": Decimal("3500.00"),
                "cpp_max_pensionable": Decimal("66600.00"),
                "cpp2_rate": Decimal("0.0400"),
                "cpp2_max_pensionable": Decimal("73200.00"),
                "ei_rate": Decimal("0.0166"),
                "ei_max_insurable": Decimal("63200.00"),
                "ei_employer_multiplier": Decimal("1.40"),
                "federal_basic_personal_amount": Decimal("15000.00"),
            },
        )
        if not created_year and tax_year.cpp_rate == Decimal("0.00") and tax_year.ei_rate == Decimal("0.00"):
            tax_year.cpp_rate = Decimal("0.0595")
            tax_year.cpp_basic_exemption = Decimal("3500.00")
            tax_year.cpp_max_pensionable = Decimal("66600.00")
            tax_year.cpp2_rate = Decimal("0.0400")
            tax_year.cpp2_max_pensionable = Decimal("73200.00")
            tax_year.ei_rate = Decimal("0.0166")
            tax_year.ei_max_insurable = Decimal("63200.00")
            tax_year.ei_employer_multiplier = Decimal("1.40")
            tax_year.federal_basic_personal_amount = Decimal("15000.00")
            tax_year.save(
                update_fields=[
                    "cpp_rate",
                    "cpp_basic_exemption",
                    "cpp_max_pensionable",
                    "cpp2_rate",
                    "cpp2_max_pensionable",
                    "ei_rate",
                    "ei_max_insurable",
                    "ei_employer_multiplier",
                    "federal_basic_personal_amount",
                ]
            )

        federal_brackets = [
            (Decimal("0.00"), Decimal("53359.00"), Decimal("0.15")),
            (Decimal("53359.00"), None, Decimal("0.205")),
        ]
        for bracket_min, bracket_max, rate in federal_brackets:
            bracket, created = PayrollTaxBracket.objects.get_or_create(
                tax_year=tax_year,
                jurisdiction=PayrollTaxBracket.JURISDICTION_FEDERAL,
                bracket_min=bracket_min,
                bracket_max=bracket_max,
                defaults={"rate": rate},
            )
            if not created and bracket.rate == Decimal("0.00"):
                bracket.rate = rate
                bracket.save(update_fields=["rate"])

        for province in provinces:
            province_setting, created = PayrollProvinceTaxSetting.objects.get_or_create(
                tax_year=tax_year,
                province=province,
                defaults={"basic_personal_amount": Decimal("11000.00")},
            )
            if not created and province_setting.basic_personal_amount == Decimal("0.00"):
                province_setting.basic_personal_amount = Decimal("11000.00")
                province_setting.save(update_fields=["basic_personal_amount"])

            provincial_brackets = [
                (Decimal("0.00"), Decimal("50000.00"), Decimal("0.0500")),
                (Decimal("50000.00"), None, Decimal("0.0900")),
            ]
            for bracket_min, bracket_max, rate in provincial_brackets:
                bracket, created = PayrollTaxBracket.objects.get_or_create(
                    tax_year=tax_year,
                    jurisdiction=province,
                    bracket_min=bracket_min,
                    bracket_max=bracket_max,
                    defaults={"rate": rate},
                )
                if not created and bracket.rate == Decimal("0.00"):
                    bracket.rate = rate
                    bracket.save(update_fields=["rate"])

            PayrollEmployerTax.objects.get_or_create(
                tax_year=tax_year,
                province=province,
                name="Employer Health Tax",
                defaults={
                    "rate": Decimal("0.0120"),
                    "threshold": Decimal("5000.00"),
                    "max_amount": None,
                    "applies_to_all": True,
                },
            )
