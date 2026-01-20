from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import calendar
import datetime
from typing import Iterable

from django.db.models import Sum
from django.utils import timezone

from .models import (
    PayrollSettings,
    PayrollTaxYear,
    PayrollProvinceTaxSetting,
    PayrollTaxBracket,
    PayrollEmployerTax,
    PayStub,
    EmployeeTaxProfile,
    EmployeeRecurringDeduction,
    TimesheetSnapshot,
)


DECIMAL_ZERO = Decimal("0.00")


def get_pay_period_for_date(settings: PayrollSettings, target_date) -> tuple[datetime.date, datetime.date]:
    if not target_date:
        today = timezone.localdate()
        return today, today

    if settings.pay_period_frequency == PayrollSettings.PAY_PERIOD_SEMIMONTHLY:
        start_day = 1 if target_date.day <= 15 else 16
        start = datetime.date(target_date.year, target_date.month, start_day)
        if start_day == 1:
            end = datetime.date(target_date.year, target_date.month, 15)
        else:
            last_day = calendar.monthrange(target_date.year, target_date.month)[1]
            end = datetime.date(target_date.year, target_date.month, last_day)
        return start, end

    if settings.pay_period_frequency == PayrollSettings.PAY_PERIOD_MONTHLY:
        start = datetime.date(target_date.year, target_date.month, 1)
        last_day = calendar.monthrange(target_date.year, target_date.month)[1]
        end = datetime.date(target_date.year, target_date.month, last_day)
        return start, end

    period_days = 7 if settings.pay_period_frequency == PayrollSettings.PAY_PERIOD_WEEKLY else 14
    anchor = settings.period_anchor_date
    delta_days = (target_date - anchor).days
    period_offset = (delta_days // period_days) * period_days
    start = anchor + datetime.timedelta(days=period_offset)
    end = start + datetime.timedelta(days=period_days - 1)
    return start, end


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return DECIMAL_ZERO


def _round_currency(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_periods_per_year(settings: PayrollSettings) -> int:
    mapping = {
        PayrollSettings.PAY_PERIOD_WEEKLY: 52,
        PayrollSettings.PAY_PERIOD_BIWEEKLY: 26,
        PayrollSettings.PAY_PERIOD_SEMIMONTHLY: 24,
        PayrollSettings.PAY_PERIOD_MONTHLY: 12,
    }
    return mapping.get(settings.pay_period_frequency, 26)


def get_tax_year(target_date) -> PayrollTaxYear | None:
    year = getattr(target_date, "year", None) or timezone.now().year
    return PayrollTaxYear.objects.filter(year=year).first()


def _sum_ytd_paystubs(employee_id: int, year: int, field: str) -> Decimal:
    total = (
        PayStub.objects.filter(employee_id=employee_id, payroll_run__period_end__year=year)
        .aggregate(total=Sum(field))
        .get("total")
    )
    return _to_decimal(total)


def _compute_tax_from_brackets(
    annual_income: Decimal,
    brackets: Iterable[PayrollTaxBracket],
    basic_personal_amount: Decimal,
) -> Decimal:
    tax = DECIMAL_ZERO
    for bracket in brackets:
        bracket_min = _to_decimal(bracket.bracket_min)
        bracket_max = _to_decimal(bracket.bracket_max) if bracket.bracket_max is not None else None
        if annual_income <= bracket_min:
            break
        taxable_portion = annual_income - bracket_min
        if bracket_max is not None:
            taxable_portion = min(taxable_portion, bracket_max - bracket_min)
        if taxable_portion > 0:
            tax += taxable_portion * _to_decimal(bracket.rate)

    lowest_rate = _to_decimal(brackets[0].rate) if brackets else DECIMAL_ZERO
    tax_credit = basic_personal_amount * lowest_rate
    tax -= tax_credit
    return max(tax, DECIMAL_ZERO)


def calculate_withholding(
    taxable_income: Decimal,
    periods_per_year: int,
    federal_brackets: Iterable[PayrollTaxBracket],
    provincial_brackets: Iterable[PayrollTaxBracket],
    federal_basic: Decimal,
    provincial_basic: Decimal,
    additional_withholding: Decimal,
) -> tuple[Decimal, Decimal]:
    annual_income = taxable_income * Decimal(periods_per_year)
    federal_tax_annual = _compute_tax_from_brackets(annual_income, federal_brackets, federal_basic)
    provincial_tax_annual = _compute_tax_from_brackets(annual_income, provincial_brackets, provincial_basic)
    federal = _round_currency(federal_tax_annual / Decimal(periods_per_year))
    provincial = _round_currency(provincial_tax_annual / Decimal(periods_per_year))
    federal += _round_currency(additional_withholding)
    return federal, provincial


@dataclass
class ContributionResult:
    employee: Decimal
    employer: Decimal


def calculate_cpp(
    taxable_income: Decimal,
    tax_year: PayrollTaxYear,
    periods_per_year: int,
    ytd_pensionable: Decimal,
    ytd_cpp: Decimal,
    ytd_cpp2: Decimal,
    cpp_exempt: bool,
    cpp2_exempt: bool,
) -> tuple[ContributionResult, ContributionResult]:
    if cpp_exempt:
        return ContributionResult(DECIMAL_ZERO, DECIMAL_ZERO), ContributionResult(DECIMAL_ZERO, DECIMAL_ZERO)

    basic_exemption = _to_decimal(tax_year.cpp_basic_exemption) / Decimal(periods_per_year)
    pensionable = max(DECIMAL_ZERO, taxable_income - basic_exemption)
    max_pensionable = _to_decimal(tax_year.cpp_max_pensionable)
    remaining_pensionable = max(DECIMAL_ZERO, max_pensionable - ytd_pensionable)
    pensionable = min(pensionable, remaining_pensionable)
    cpp_rate = _to_decimal(tax_year.cpp_rate)
    cpp_employee = _round_currency(pensionable * cpp_rate)
    cpp_employer = cpp_employee

    cpp2_employee = DECIMAL_ZERO
    cpp2_employer = DECIMAL_ZERO
    if not cpp2_exempt and _to_decimal(tax_year.cpp2_rate) > 0 and _to_decimal(tax_year.cpp2_max_pensionable) > 0:
        cpp2_rate = _to_decimal(tax_year.cpp2_rate)
        cpp2_max = _to_decimal(tax_year.cpp2_max_pensionable)
        cpp_max = _to_decimal(tax_year.cpp_max_pensionable)
        ytd_cpp2_pensionable = max(DECIMAL_ZERO, ytd_pensionable - cpp_max)
        available_cpp2 = max(DECIMAL_ZERO, cpp2_max - cpp_max - ytd_cpp2_pensionable)
        current_cpp2_base = max(DECIMAL_ZERO, (ytd_pensionable + pensionable) - cpp_max) - ytd_cpp2_pensionable
        cpp2_base = min(available_cpp2, current_cpp2_base)
        cpp2_employee = _round_currency(cpp2_base * cpp2_rate)
        cpp2_employer = cpp2_employee

    return ContributionResult(cpp_employee, cpp_employer), ContributionResult(cpp2_employee, cpp2_employer)


def calculate_ei(
    taxable_income: Decimal,
    tax_year: PayrollTaxYear,
    ytd_insurable: Decimal,
    ei_exempt: bool,
) -> ContributionResult:
    if ei_exempt:
        return ContributionResult(DECIMAL_ZERO, DECIMAL_ZERO)

    max_insurable = _to_decimal(tax_year.ei_max_insurable)
    remaining_insurable = max(DECIMAL_ZERO, max_insurable - ytd_insurable)
    insurable = min(taxable_income, remaining_insurable)
    ei_rate = _to_decimal(tax_year.ei_rate)
    ei_employee = _round_currency(insurable * ei_rate)
    ei_employer = _round_currency(ei_employee * _to_decimal(tax_year.ei_employer_multiplier))
    return ContributionResult(ei_employee, ei_employer)


def calculate_employer_taxes(
    taxable_income: Decimal,
    tax_year: PayrollTaxYear,
    province: str,
    ytd_payroll: Decimal,
) -> list[tuple[str, Decimal]]:
    taxes = []
    rules = PayrollEmployerTax.objects.filter(tax_year=tax_year, province=province)
    for rule in rules:
        threshold = _to_decimal(rule.threshold)
        if (ytd_payroll + taxable_income) <= threshold:
            continue
        taxable_base = taxable_income
        amount = _round_currency(taxable_base * _to_decimal(rule.rate))
        if rule.max_amount is not None:
            amount = min(amount, _to_decimal(rule.max_amount))
        if amount > 0:
            taxes.append((rule.name, amount))
    return taxes


def calculate_timesheet_hours(entries, settings: PayrollSettings) -> tuple[Decimal, Decimal, Decimal]:
    daily_hours = {}
    for entry in entries:
        hours = _to_decimal(entry.hours)
        if not entry.work_date:
            continue
        daily_hours[entry.work_date] = daily_hours.get(entry.work_date, DECIMAL_ZERO) + hours

    total_hours = sum(daily_hours.values(), DECIMAL_ZERO)
    if not settings.overtime_enabled:
        return total_hours, total_hours, DECIMAL_ZERO

    daily_threshold = _to_decimal(settings.overtime_daily_threshold) if settings.overtime_daily_enabled else DECIMAL_ZERO
    weekly_threshold = _to_decimal(settings.overtime_weekly_threshold) if settings.overtime_weekly_enabled else DECIMAL_ZERO

    daily_regular_hours = {}
    overtime_hours = DECIMAL_ZERO
    for day, hours in daily_hours.items():
        regular_for_day = hours
        if settings.overtime_daily_enabled and daily_threshold > 0 and hours > daily_threshold:
            overtime_hours += hours - daily_threshold
            regular_for_day = daily_threshold
        daily_regular_hours[day] = regular_for_day

    weekly_regular_hours = {}
    for day, regular_for_day in daily_regular_hours.items():
        week_start = day - datetime.timedelta(days=day.weekday())
        weekly_regular_hours[week_start] = weekly_regular_hours.get(week_start, DECIMAL_ZERO) + regular_for_day

    if settings.overtime_weekly_enabled and weekly_threshold > 0:
        for week_start, regular_for_week in weekly_regular_hours.items():
            if regular_for_week > weekly_threshold:
                weekly_overtime = regular_for_week - weekly_threshold
                overtime_hours += weekly_overtime
                weekly_regular_hours[week_start] = weekly_threshold

    regular_hours = sum(weekly_regular_hours.values(), DECIMAL_ZERO)

    return total_hours, regular_hours, overtime_hours


def build_timesheet_snapshot_payload(timesheet, entries=None) -> tuple[list[dict], Decimal]:
    entries_qs = entries if entries is not None else timesheet.entries.all().order_by("work_date", "start_time")
    payload = []
    total_hours = DECIMAL_ZERO
    for entry in entries_qs:
        hours = _to_decimal(entry.hours)
        total_hours += hours
        payload.append(
            {
                "work_date": entry.work_date.isoformat() if entry.work_date else "",
                "start_time": entry.start_time.strftime("%H:%M") if entry.start_time else "",
                "end_time": entry.end_time.strftime("%H:%M") if entry.end_time else "",
                "hours": f"{hours:.2f}",
                "notes": entry.notes or "",
            }
        )
    return payload, total_hours


def upsert_timesheet_snapshot(timesheet, source: str, submitted_by=None) -> TimesheetSnapshot:
    entries, total_hours = build_timesheet_snapshot_payload(timesheet)
    snapshot, _ = TimesheetSnapshot.objects.update_or_create(
        timesheet=timesheet,
        source=source,
        defaults={
            "submitted_by": submitted_by,
            "total_hours": total_hours,
            "entries": entries,
        },
    )
    return snapshot


def compare_timesheet_entries(reference_entries, submitted_entries) -> list[dict]:
    def _normalize(entry):
        entry = entry or {}
        return {
            "start_time": str(entry.get("start_time") or "").strip(),
            "end_time": str(entry.get("end_time") or "").strip(),
            "hours": str(entry.get("hours") or "").strip(),
            "notes": str(entry.get("notes") or "").strip(),
        }

    def _build_map(entries):
        entry_map = {}
        for item in entries or []:
            date_key = item.get("work_date") or ""
            if date_key:
                entry_map[date_key] = item
        return entry_map

    reference_map = _build_map(reference_entries)
    submitted_map = _build_map(submitted_entries)
    differences = []
    for date_key in sorted(set(reference_map) | set(submitted_map)):
        reference_entry = _normalize(reference_map.get(date_key))
        submitted_entry = _normalize(submitted_map.get(date_key))
        diff_fields = {}
        for field in ("start_time", "end_time", "hours", "notes"):
            if reference_entry[field] != submitted_entry[field]:
                diff_fields[field] = True
        if diff_fields:
            differences.append(
                {
                    "work_date": date_key,
                    "reference": reference_entry,
                    "submitted": submitted_entry,
                    "diff_fields": diff_fields,
                }
            )
    return differences


def calculate_employee_pay(
    employee,
    period_start,
    period_end,
    hours: Decimal,
    settings: PayrollSettings,
    regular_hours: Decimal | None = None,
    overtime_hours: Decimal | None = None,
):
    try:
        tax_profile = employee.tax_profile
    except EmployeeTaxProfile.DoesNotExist:
        raise ValueError("Employee tax profile is missing.")
    tax_year = get_tax_year(period_end)
    if not tax_year:
        raise ValueError("Missing payroll tax year configuration.")

    periods_per_year = get_periods_per_year(settings)
    hourly_rate = _to_decimal(employee.hourly_rate)
    total_hours = _to_decimal(hours)
    if regular_hours is None and overtime_hours is None:
        regular_hours = total_hours
        overtime_hours = DECIMAL_ZERO
    else:
        regular_hours = _to_decimal(regular_hours or DECIMAL_ZERO)
        overtime_hours = _to_decimal(overtime_hours or DECIMAL_ZERO)
        total_hours = regular_hours + overtime_hours

    if settings.overtime_enabled:
        overtime_multiplier = _to_decimal(settings.overtime_multiplier)
        regular_pay = regular_hours * hourly_rate
        overtime_pay = overtime_hours * hourly_rate * overtime_multiplier
        gross_pay = _round_currency(regular_pay + overtime_pay)
    else:
        regular_hours = total_hours
        overtime_hours = DECIMAL_ZERO
        regular_pay = total_hours * hourly_rate
        overtime_pay = DECIMAL_ZERO
        gross_pay = _round_currency(regular_pay)

    pre_tax_deductions = EmployeeRecurringDeduction.objects.filter(
        employee=employee, active=True, is_pre_tax=True, is_employee_contribution=True
    )
    pre_tax_total = sum((_to_decimal(d.amount) for d in pre_tax_deductions), DECIMAL_ZERO)
    taxable_income = max(DECIMAL_ZERO, gross_pay - pre_tax_total)

    federal_brackets = PayrollTaxBracket.objects.filter(
        tax_year=tax_year, jurisdiction=PayrollTaxBracket.JURISDICTION_FEDERAL
    ).order_by("bracket_min")
    provincial_brackets = PayrollTaxBracket.objects.filter(
        tax_year=tax_year, jurisdiction=tax_profile.province
    ).order_by("bracket_min")
    if not federal_brackets.exists() or not provincial_brackets.exists():
        raise ValueError("Payroll tax brackets are not configured for this year/province.")

    ytd_taxable = _sum_ytd_paystubs(employee.id, period_end.year, "taxable_income")
    ytd_cppable = _sum_ytd_paystubs(employee.id, period_end.year, "taxable_income")
    ytd_cpp = _sum_ytd_paystubs(employee.id, period_end.year, "cpp_employee")
    ytd_cpp2 = _sum_ytd_paystubs(employee.id, period_end.year, "cpp2_employee")
    ytd_ei_insurable = _sum_ytd_paystubs(employee.id, period_end.year, "taxable_income")

    federal_claim = _to_decimal(tax_profile.federal_claim_amount)
    if federal_claim <= 0:
        federal_claim = _to_decimal(tax_year.federal_basic_personal_amount)

    provincial_claim = _to_decimal(tax_profile.provincial_claim_amount)
    if provincial_claim <= 0:
        province_setting = PayrollProvinceTaxSetting.objects.filter(
            tax_year=tax_year, province=tax_profile.province
        ).first()
        if province_setting:
            provincial_claim = _to_decimal(province_setting.basic_personal_amount)

    federal_tax, provincial_tax = calculate_withholding(
        taxable_income=taxable_income,
        periods_per_year=periods_per_year,
        federal_brackets=federal_brackets,
        provincial_brackets=provincial_brackets,
        federal_basic=federal_claim,
        provincial_basic=provincial_claim,
        additional_withholding=_to_decimal(tax_profile.additional_withholding),
    )

    cpp_result, cpp2_result = calculate_cpp(
        taxable_income=taxable_income,
        tax_year=tax_year,
        periods_per_year=periods_per_year,
        ytd_pensionable=ytd_cppable,
        ytd_cpp=ytd_cpp,
        ytd_cpp2=ytd_cpp2,
        cpp_exempt=tax_profile.cpp_exempt,
        cpp2_exempt=tax_profile.cpp2_exempt,
    )

    ei_result = calculate_ei(
        taxable_income=taxable_income,
        tax_year=tax_year,
        ytd_insurable=ytd_ei_insurable,
        ei_exempt=tax_profile.ei_exempt,
    )

    other_employee_deductions = EmployeeRecurringDeduction.objects.filter(
        employee=employee, active=True, is_employee_contribution=True, is_pre_tax=False
    )
    other_deductions_total = sum((_to_decimal(d.amount) for d in other_employee_deductions), DECIMAL_ZERO)

    employer_contributions = EmployeeRecurringDeduction.objects.filter(
        employee=employee, active=True, is_employer_contribution=True
    )
    employer_contribution_total = sum((_to_decimal(d.amount) for d in employer_contributions), DECIMAL_ZERO)

    net_pay = gross_pay - pre_tax_total - federal_tax - provincial_tax - cpp_result.employee - cpp2_result.employee - ei_result.employee - other_deductions_total
    net_pay = _round_currency(max(net_pay, DECIMAL_ZERO))

    employer_taxes = calculate_employer_taxes(
        taxable_income=taxable_income,
        tax_year=tax_year,
        province=tax_profile.province,
        ytd_payroll=ytd_taxable,
    )
    employer_tax_total = sum((amount for _, amount in employer_taxes), DECIMAL_ZERO)

    employer_total = cpp_result.employer + cpp2_result.employer + ei_result.employer + employer_tax_total + employer_contribution_total

    return {
        "tax_year": tax_year,
        "total_hours": total_hours,
        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "regular_pay": _round_currency(regular_pay),
        "overtime_pay": _round_currency(overtime_pay),
        "gross_pay": gross_pay,
        "taxable_income": taxable_income,
        "pre_tax_deductions": pre_tax_total,
        "federal_tax": federal_tax,
        "provincial_tax": provincial_tax,
        "cpp_employee": cpp_result.employee,
        "cpp_employer": cpp_result.employer,
        "cpp2_employee": cpp2_result.employee,
        "cpp2_employer": cpp2_result.employer,
        "ei_employee": ei_result.employee,
        "ei_employer": ei_result.employer,
        "other_deductions": other_deductions_total,
        "net_pay": net_pay,
        "employer_taxes": employer_taxes,
        "employer_contributions": employer_contributions,
        "employer_contribution_total": employer_contribution_total,
        "employer_total": _round_currency(employer_total),
    }
