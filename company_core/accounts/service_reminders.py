"""Utility helpers for creating maintenance reminders from selected services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Sequence

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from .models import Service, Vehicle, VehicleMaintenanceTask


logger = logging.getLogger(__name__)


@dataclass
class SelectedServiceEntry:
    """Normalized payload representing a selected reusable service."""

    service: Service
    job_text: str
    due_after_kilometers: int | None = None
    due_after_months: int | None = None
    line_number: int | None = None


def _parse_positive_int(value: object) -> int | None:
    if value in (None, "", [], {}, ()):  # pragma: no cover - defensive
        return None
    try:
        numeric_value = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return numeric_value if numeric_value >= 0 else None


def _normalize_job_text(value: str | None) -> str:
    return (value or "").strip()


def _extract_management_total(post_data, prefix: str) -> int:
    raw_total = post_data.get(f"{prefix}-TOTAL_FORMS")
    if raw_total in (None, ""):
        return 0
    try:
        return int(raw_total)
    except (TypeError, ValueError):
        return 0


def parse_service_entries(post_data, *, prefix: str, user) -> List[SelectedServiceEntry]:
    """Return structured service selections parsed from a POSTed formset."""

    if not user:
        return []

    total_forms = _extract_management_total(post_data, prefix)
    if total_forms <= 0:
        return []

    entries: List[SelectedServiceEntry] = []

    for index in range(total_forms):
        delete_flag = post_data.get(f"{prefix}-{index}-DELETE")
        if str(delete_flag).lower() in {"on", "true", "1"}:
            continue

        skip_flag = post_data.get(f"{prefix}-{index}-skip_maintenance")
        if str(skip_flag).lower() in {"on", "true", "1", "yes"}:
            logger.debug(
                "Skipping maintenance creation for %s-%s due to explicit opt-out.",
                prefix,
                index,
            )
            continue

        raw_service_id = (post_data.get(f"{prefix}-{index}-service_id") or "").strip()
        if not raw_service_id:
            continue
        try:
            service_id = int(raw_service_id)
        except (TypeError, ValueError):
            continue

        service = (
            Service.objects.filter(pk=service_id, user=user)
            .select_related("job_name")
            .first()
        )
        if not service:
            continue

        due_after_kilometers = _parse_positive_int(
            post_data.get(f"{prefix}-{index}-service_due_kilometers")
        )
        due_after_months = _parse_positive_int(
            post_data.get(f"{prefix}-{index}-service_due_months")
        )
        job_text = _normalize_job_text(post_data.get(f"{prefix}-{index}-job"))

        entries.append(
            SelectedServiceEntry(
                service=service,
                job_text=job_text,
                due_after_kilometers=due_after_kilometers,
                due_after_months=due_after_months,
                line_number=index + 1,
            )
        )

    return entries


def _normalize_base_mileage(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    normalized = decimal_value.quantize(Decimal("1"))
    return int(normalized)


def _calculate_due_date(base_date: date | None, due_after_months: int | None) -> date | None:
    if not base_date or due_after_months in (None, ""):
        return None
    try:
        return base_date + relativedelta(months=+int(due_after_months))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _calculate_due_mileage(base_mileage: int | None, due_after_km: int | None) -> int | None:
    if base_mileage is None or due_after_km in (None, ""):
        return None
    try:
        return int(base_mileage) + int(due_after_km)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _maybe_update_service_due_fields(service: Service, *, km: int | None, months: int | None):
    fields_to_update: List[str] = []
    if km is not None and service.due_after_kilometers is None:
        service.due_after_kilometers = km
        fields_to_update.append("due_after_kilometers")
    if months is not None and service.due_after_months is None:
        service.due_after_months = months
        fields_to_update.append("due_after_months")
    if fields_to_update:
        fields_to_update.append("updated_at")
        service.save(update_fields=fields_to_update)


def _build_task_title(
    base_title: str,
    *,
    last_done_mileage: int | None,
    last_done_date: date | None,
) -> str:
    """Return a descriptive title that captures the last completed mileage/date."""

    normalized_title = (base_title or "Scheduled maintenance").strip()
    detail_segments: List[str] = []
    if last_done_mileage is not None:
        detail_segments.append(f"{last_done_mileage:,} kms")
    if last_done_date is not None:
        detail_segments.append(last_done_date.isoformat())

    if detail_segments:
        normalized_title = (
            f"{normalized_title} - Last done on "
            f"{' and '.join(detail_segments)}"
        )

    if len(normalized_title) > 120:
        normalized_title = normalized_title[:117].rstrip() + "..."

    return normalized_title


def create_maintenance_tasks_from_services(
    service_entries: Sequence[SelectedServiceEntry],
    *,
    vehicle: Vehicle | None,
    user,
    base_date: date | None,
    base_mileage,
    source_label: str,
    work_order=None,
    grouped_invoice=None,
) -> List[VehicleMaintenanceTask]:
    """Persist maintenance reminders for the provided service selections."""

    if not vehicle or not user or not service_entries:
        return []

    normalized_base_date = base_date or timezone.localdate()
    normalized_mileage = _normalize_base_mileage(base_mileage)
    last_completed_date = base_date if base_date else None

    tasks: List[VehicleMaintenanceTask] = []

    for entry in service_entries:
        due_after_months = entry.due_after_months or entry.service.due_after_months
        due_after_km = entry.due_after_kilometers or entry.service.due_after_kilometers

        due_date = _calculate_due_date(normalized_base_date, due_after_months)
        due_mileage = _calculate_due_mileage(normalized_mileage, due_after_km)

        if due_date is None and due_mileage is None:
            logger.debug(
                "Skipping service %s because no due information was available.",
                entry.service.id,
            )
            continue

        _maybe_update_service_due_fields(entry.service, km=due_after_km, months=due_after_months)

        note_parts: List[str] = []
        if source_label:
            note_parts.append(f"Auto-created from {source_label}.")
        if entry.line_number is not None:
            note_parts.append(f"Line {entry.line_number}.")
        if entry.job_text:
            note_parts.append(f"Service: {entry.job_text}")

        description = " ".join(part for part in note_parts if part)
        base_title = (
            getattr(entry.service, "job_name", None) and entry.service.job_name.name
        ) or entry.service.name or "Scheduled maintenance"

        title = _build_task_title(
            base_title,
            last_done_mileage=normalized_mileage,
            last_done_date=last_completed_date,
        )

        task = VehicleMaintenanceTask.objects.create(
            vehicle=vehicle,
            user=user,
            title=title or "Scheduled maintenance",
            description=description,
            due_date=due_date,
            due_mileage=due_mileage,
            mileage_interval=due_after_km,
            priority=VehicleMaintenanceTask.PRIORITY_MEDIUM,
            status=VehicleMaintenanceTask.STATUS_PLANNED,
            work_order=work_order,
            grouped_invoice=grouped_invoice,
        )
        tasks.append(task)

    if tasks:
        logger.info(
            "Created %s maintenance reminder(s) for vehicle %s from %s.",
            len(tasks),
            vehicle.id,
            source_label,
        )

    return tasks

