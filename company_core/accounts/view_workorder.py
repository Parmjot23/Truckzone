# views_workorder.py (Cleaned)

import base64
import json
import logging
import uuid
from datetime import datetime, date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.transaction import TransactionManagementError
from django.db.models import Q, Sum
from django.db.models.functions import Lower
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.dateparse import parse_time
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from decimal import Decimal
from dateutil.relativedelta import relativedelta
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    HTML = None

from .ai_service import refine_cause_correction, autocorrect_text_block, transcribe_audio_and_rephrase

from .utils import resolve_company_logo_url, get_customer_user_ids, get_product_user_ids
from .pdf_utils import apply_branding_defaults, render_template_to_pdf

from .models import (
    Customer,
    Employee,
    GroupedInvoice,
    IncomeRecord2,
    InventoryTransaction,
    Mechanic,
    MechanicSignupCode,
    PayStub,
    PendingInvoice,
    PayrollSettings,
    Product,
    Category,
    Service,
    ServiceJobName,
    TimeEntry,
    Timesheet,
    TimesheetSnapshot,
    Vehicle,
    VehicleMaintenanceTask,
    PMInspection,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderRecord,
)
from .forms import (
    MechanicProductUsageRecordInlineFormSet,
    WorkOrderForm,
    WorkOrderRecordForm,
    WorkOrderRecordFormSet,
    CustomerForm,
    MechanicWorkOrderForm,
    MechanicForm,
    MechanicBasicForm,
    MechanicSignupForm,
    VehicleForm,
    VehicleQuickWorkOrderForm,
    WorkOrderReassignForm,
)
from .utils import (
    notify_customer_work_started,
    notify_mechanic_assignment,
    notify_mechanic_rework,
    sync_workorder_assignments,
)
from .payroll_utils import get_pay_period_for_date, upsert_timesheet_snapshot
from .service_reminders import (
    create_maintenance_tasks_from_services,
    parse_service_entries,
)
# Assuming decorators are in 'accounts.decorators' based on original code
from accounts.decorators import activation_required, subscription_required


logger = logging.getLogger(__name__)


def _format_workorder_exception(exc: Exception) -> str:
    """Return a user-friendly message for unexpected work order errors."""

    message = str(exc).strip()

    if isinstance(exc, TransactionManagementError):
        cause = getattr(exc, "__cause__", None)
        cause_message = str(cause).strip() if cause else ""

        if cause_message:
            message = cause_message

        if not message or "current transaction" in message.lower():
            message = (
                "The previous database transaction was rolled back. "
                "Please review the work order details and try saving again."
            )

    if not message:
        message = "An unknown error occurred."

    return message


def _build_service_job_catalog(user):
    """Return job catalog data backed by saved service templates."""

    job_names = (
        ServiceJobName.objects.filter(user=user, is_active=True)
        .prefetch_related('services')
        .order_by(Lower('name'))
    )

    catalog = []
    description_strings = []

    for job in job_names:
        services = [
            {
                'id': service.id,
                'text': service.name,
                'notes': service.description or '',
                'fixed_hours': str(service.fixed_hours) if service.fixed_hours is not None else '',
                'fixed_rate': str(service.fixed_rate) if service.fixed_rate is not None else '',
                'due_after_kilometers': service.due_after_kilometers or '',
                'due_after_months': service.due_after_months or '',
            }
            for service in job.services.filter(is_active=True).order_by(Lower('name'))
        ]

        if not services:
            continue

        catalog.append(
            {
                'id': job.id,
                'name': job.name,
                'descriptions': services,
            }
        )

        description_strings.extend(item['text'] for item in services)

    return catalog, description_strings


def _validate_completed_line_items(workorder_form, formset):
    """Ensure completed work orders include at least one fully priced line item."""

    status = (workorder_form.cleaned_data.get('status') or '').strip()
    if status != 'completed':
        return True

    has_valid_line = False
    for form in formset.forms:
        cleaned = getattr(form, 'cleaned_data', None) or {}
        if cleaned.get('DELETE'):
            continue

        job_text = (cleaned.get('job') or '').strip()
        product = cleaned.get('product')
        qty = cleaned.get('qty')
        rate = cleaned.get('rate')

        if not (job_text or product or qty not in (None, '') or rate not in (None, '')):
            continue

        if not (job_text or product):
            form.add_error('job', 'Description or product is required to complete the work order.')
        if qty in (None, ''):
            form.add_error('qty', 'Quantity is required to complete the work order.')
        if rate in (None, ''):
            form.add_error('rate', 'Rate is required to complete the work order.')

        if (job_text or product) and qty not in (None, '') and rate not in (None, ''):
            has_valid_line = True

    if not has_valid_line:
        workorder_form.add_error(
            'status',
            'Add at least one line item with quantity and rate before completing the work order.',
        )
        return False

    return True


def _build_vehicle_summary(vehicle):
    if not vehicle:
        return None

    vehicle_label_parts = []
    if vehicle.unit_number:
        vehicle_label_parts.append(f"Unit {vehicle.unit_number}")
    if vehicle.make_model:
        vehicle_label_parts.append(vehicle.make_model)
    if not vehicle_label_parts and vehicle.vin_number:
        vehicle_label_parts.append(vehicle.vin_number)

    return {
        "id": vehicle.id,
        "unit_number": vehicle.unit_number or "",
        "vin": vehicle.vin_number or "",
        "make_model": vehicle.make_model or "",
        "label": " • ".join(vehicle_label_parts) if vehicle_label_parts else "Vehicle",
    }


def _serialize_vehicle_history(vehicle, *, limit=50, mechanic_view=False):
    """Return a dictionary describing a vehicle's recent job history."""

    payload = {
        "vehicle": _build_vehicle_summary(vehicle),
        "jobs": [],
        "parts": [],
        "has_history": False,
    }

    if not vehicle:
        return payload

    history_qs = (
        vehicle.job_history.exclude(description__iexact="shop supply")
        .exclude(description__iexact="discount")
        .order_by("-job_date", "-id")
        .select_related("source_income_record", "source_income_record__product")
    )

    def _format_decimal(value):
        if value is None:
            return ""
        if isinstance(value, Decimal):
            normalized = value.normalize()
            return format(normalized)
        return str(value)

    for entry in history_qs[:limit]:
        entry_date_display = (
            date_format(entry.job_date, format="DATE_FORMAT") if entry.job_date else ""
        )
        entry_date_iso = entry.job_date.isoformat() if entry.job_date else None
        source = getattr(entry, "source_income_record", None)
        product = getattr(source, "product", None)

        if product:
            quantity = getattr(source, "qty", None)
            payload["parts"].append(
                {
                    "id": entry.id,
                    "date": entry_date_display,
                    "date_iso": entry_date_iso,
                    "description": product.name or (entry.description or ""),
                    "quantity": _format_decimal(quantity),
                }
            )
            continue

        job_info = {
            "id": entry.id,
            "date": entry_date_display,
            "date_iso": entry_date_iso,
            "description": entry.description or "",
        }
        if entry.notes:
            job_info["notes"] = entry.notes
        if not mechanic_view:
            job_info["cost"] = f"${entry.total_job_cost:.2f}"
        payload["jobs"].append(job_info)

    payload["has_history"] = bool(payload["jobs"] or payload["parts"])
    return payload


def _serialize_vehicle_maintenance(vehicle, *, limit=25):
    """Return a dictionary describing active maintenance reminders for a vehicle."""

    payload = {
        "vehicle": _build_vehicle_summary(vehicle),
        "tasks": [],
        "has_tasks": False,
        "active_count": 0,
        "overdue_count": 0,
    }

    if not vehicle:
        return payload

    active_statuses = VehicleMaintenanceTask.active_statuses()
    tasks_qs = (
        vehicle.maintenance_tasks.filter(status__in=active_statuses)
        .order_by("due_date", "due_mileage", "title")
    )

    today = timezone.localdate()
    overdue_count = 0

    for task in tasks_qs[:limit]:
        due_parts = []
        if task.due_date:
            due_parts.append(
                date_format(task.due_date, format="DATE_FORMAT")
            )
        if task.due_mileage:
            due_parts.append(f"{int(task.due_mileage):,} km")
        due_display = " • ".join(due_parts) or "Due date not set"
        is_overdue = bool(task.due_date and task.due_date < today)
        if is_overdue:
            overdue_count += 1

        payload["tasks"].append(
            {
                "id": task.id,
                "title": task.title or "Maintenance reminder",
                "description": task.description or "",
                "due_display": due_display,
                "due_date": date_format(task.due_date, format="DATE_FORMAT") if task.due_date else "",
                "due_date_iso": task.due_date.isoformat() if task.due_date else None,
                "due_mileage": int(task.due_mileage) if task.due_mileage is not None else None,
                "due_mileage_display": f"{int(task.due_mileage):,} km" if task.due_mileage else "",
                "priority": task.priority,
                "priority_label": task.get_priority_display(),
                "status": task.status,
                "status_label": task.get_status_display(),
                "is_overdue": is_overdue,
            }
        )

    payload["has_tasks"] = bool(payload["tasks"])
    payload["active_count"] = len(payload["tasks"])
    payload["overdue_count"] = overdue_count
    return payload


def _resolve_vehicle_from_form(form):
    vehicle = getattr(getattr(form, "instance", None), "vehicle", None)
    if vehicle:
        return vehicle

    try:
        raw_value = form["vehicle"].value()
        field = form.fields.get("vehicle")
    except Exception:  # pragma: no cover - defensive
        raw_value = None
        field = None

    if raw_value and field is not None:
        try:
            return field.queryset.filter(pk=raw_value).first()
        except (TypeError, ValueError):
            return None
    return None


PM_CHECKLIST_SECTIONS = [
    {
        "code": "A",
        "title": "Instruments & Controls",
        "items": [
            {"id": "instruments-accelerator-pedal", "code": "a", "label": "Accelerator pedal"},
            {"id": "instruments-brake-pedal", "code": "b", "label": "Brake pedal"},
            {"id": "instruments-clutch", "code": "c", "label": "Clutch"},
            {"id": "instruments-engine-shutdown", "code": "d", "label": "Engine shut down"},
            {"id": "instruments-neutral-safety-switch", "code": "e", "label": "Neutral safety switch"},
            {"id": "instruments-shift-pattern", "code": "f", "label": "Shift pattern / if equipped"},
            {"id": "instruments-controls-switches", "code": "g", "label": "Controls, switches"},
            {"id": "instruments-indicators", "code": "h", "label": "Instrument / indicator / lamp"},
            {"id": "instruments-speedometer", "code": "i", "label": "Speedometer"},
            {"id": "instruments-steering-travel", "code": "j", "label": "Steering wheel & travel"},
            {"id": "instruments-steering-tilt", "code": "k", "label": "Steering wheel tilt & telescope"},
            {"id": "instruments-horn", "code": "l", "label": "Horn"},
            {"id": "instruments-wipers", "code": "m", "label": "Windshield wiper & washer"},
            {"id": "instruments-heater-defroster", "code": "n", "label": "Heater / defroster"},
        ],
    },
    {
        "code": "B",
        "title": "Interior & Equipment",
        "items": [
            {"id": "interior-windshield", "code": "a", "label": "Windshield"},
            {"id": "interior-side-windows", "code": "b", "label": "Side windows"},
            {"id": "interior-rear-window", "code": "c", "label": "Rear window"},
            {"id": "interior-rearview-mirrors", "code": "d", "label": "Rearview mirrors"},
            {"id": "interior-sun-visor", "code": "e", "label": "Sun visor"},
            {"id": "interior-fire-extinguisher", "code": "f", "label": "Fire extinguisher"},
            {"id": "interior-hazard-warning-kit", "code": "g", "label": "Hazard warning kit"},
            {"id": "interior-seats-belts-airbags", "code": "h", "label": "Seats, seat belts, air bags"},
        ],
    },
    {
        "code": "C",
        "title": "Body & Exterior",
        "items": [
            {"id": "exterior-body", "code": "a", "label": "Body & cargo body"},
            {"id": "exterior-hood", "code": "b", "label": "Hood"},
            {"id": "exterior-cab-mounts", "code": "c", "label": "Cab mounts, suspension or tilt"},
            {"id": "exterior-doors", "code": "d", "label": "Doors"},
            {"id": "exterior-grab-handles", "code": "e", "label": "Grab handle & step"},
            {"id": "exterior-bumper", "code": "f", "label": "Bumper"},
            {"id": "exterior-fenders", "code": "g", "label": "Fenders & mud flaps"},
            {"id": "exterior-load-securement", "code": "h", "label": "Load securement points"},
            {"id": "exterior-headache-rack", "code": "i", "label": "Chain / headache rack"},
            {"id": "exterior-attached-equipment", "code": "j", "label": "Attached equipment"},
            {"id": "exterior-cmvss-label", "code": "k", "label": "CMVSS compliance label"},
        ],
    },
    {
        "code": "D",
        "title": "Lamps",
        "items": [
            {"id": "lamps-headlamp-daytime", "code": "a", "label": "Headlamp, & daytime lights"},
            {"id": "lamps-tail-marker", "code": "b", "label": "Tail, marker, I.D. & clearance"},
            {"id": "lamps-brake-turn-hazard", "code": "c", "label": "Brake, turn & hazard"},
            {"id": "lamps-driving-fog-licence", "code": "d", "label": "Driving, fog & licence plate"},
            {"id": "lamps-reflectors", "code": "e", "label": "Reflector, reflective tape / mudflap"},
        ],
    },
    {
        "code": "E",
        "title": "Powertrain & Frame",
        "items": [
            {"id": "powertrain-fuel-system", "code": "a", "label": "Fuel system"},
            {"id": "powertrain-exhaust", "code": "b", "label": "Exhaust"},
            {"id": "powertrain-frame-rails", "code": "c", "label": "Frame rails, mounts"},
            {"id": "powertrain-drive-shaft", "code": "d", "label": "Drive shaft"},
            {"id": "powertrain-engine-mounts", "code": "e", "label": "Engine / trans. mounts"},
            {"id": "powertrain-power-steering", "code": "f", "label": "Power steering"},
            {"id": "powertrain-battery", "code": "g", "label": "Battery"},
            {"id": "powertrain-wiring", "code": "h", "label": "Wiring"},
        ],
    },
    {
        "code": "F",
        "title": "Steering & Suspension",
        "items": [
            {"id": "steering-linkage", "code": "a", "label": "Steering linkage"},
            {"id": "steering-ball-joints", "code": "b", "label": "Ball joints, kingpins"},
            {"id": "steering-spring-elements", "code": "c", "label": "Spring elements & attachment"},
            {"id": "steering-brackets", "code": "d", "label": "Brackets, arms, linkage"},
            {"id": "steering-air-suspension", "code": "e", "label": "Air suspension, tag axle"},
            {"id": "steering-shock-absorbers", "code": "f", "label": "Shock absorbers"},
        ],
    },
    {
        "code": "G",
        "title": "Air Brake System",
        "items": [
            {"id": "air-brake-compressor", "code": "a", "label": "Compressor"},
            {"id": "air-brake-build-up", "code": "b", "label": "Build up, governor, leakage"},
            {"id": "air-brake-low-pressure-warning", "code": "c", "label": "Low pressure warning"},
            {"id": "air-brake-check-valves", "code": "d", "label": "One & two-way check valves"},
            {"id": "air-brake-controls-valves", "code": "e", "label": "Controls, valves, lines & fittings"},
            {"id": "air-brake-tractor-protection", "code": "f", "label": "Tractor protection system"},
            {"id": "air-brake-parking-emergency", "code": "g", "label": "Parking / emergency operation"},
            {"id": "air-brake-mechanical-components", "code": "h", "label": "Mechanical components"},
            {"id": "air-brake-drum-lining", "code": "i", "label": "Drum & lining / for cracks"},
            {"id": "air-brake-rotor-caliper", "code": "j", "label": "Rotor & caliper / for cracks"},
            {"id": "air-brake-wheel-seals", "code": "k", "label": "Check for wheel seal leaks"},
            {"id": "air-brake-abs", "code": "l", "label": "ABS / no malfunction lights"},
            {"id": "air-brake-stroke", "code": "m", "label": "Brake stroke (adjustment)"},
        ],
    },
    {
        "code": "H",
        "title": "Tire & Wheel",
        "items": [
            {"id": "tire-tread-condition", "code": "a", "label": "Tread condition"},
            {"id": "tire-sidewall-damage", "code": "b", "label": "Sidewall damage"},
        ],
    },
    {
        "code": "I",
        "title": "Coupling Device",
        "items": [
            {"id": "coupling-device-fifth-wheel", "code": "a", "label": "Fifth wheel, trailer hitch"},
            {"id": "coupling-device-cords", "code": "b", "label": "Trailer air and electrical cords"},
        ],
    },
]


PUSHROD_MEASUREMENT_FIELDS = [
    {"id": "pushrod-lc", "label": "LM", "unit": "in./16"},
    {"id": "pushrod-lr", "label": "LR", "unit": "in./16"},
    {"id": "pushrod-rc", "label": "RM", "unit": "in./16"},
    {"id": "pushrod-rr", "label": "RR", "unit": "in./16"},
]

TREAD_DEPTH_FIELDS = [
    {"id": "tire-depth-lf", "label": "LF", "unit": "/32"},
    {"id": "tire-depth-lmo", "label": "LM Outer", "unit": "/32"},
    {"id": "tire-depth-lmi", "label": "LM Inner", "unit": "/32"},
    {"id": "tire-depth-lro", "label": "LR Outer", "unit": "/32"},
    {"id": "tire-depth-lri", "label": "LR Inner", "unit": "/32"},
    {"id": "tire-depth-rf", "label": "RF", "unit": "/32"},
    {"id": "tire-depth-rmo", "label": "RM Outer", "unit": "/32"},
    {"id": "tire-depth-rmi", "label": "RM Inner", "unit": "/32"},
    {"id": "tire-depth-rro", "label": "RR Outer", "unit": "/32"},
    {"id": "tire-depth-rri", "label": "RR Inner", "unit": "/32"},
]

TIRE_PRESSURE_FIELDS = [
    {"id": "tire-pressure-lf", "label": "LF", "unit": "psi"},
    {"id": "tire-pressure-lmo", "label": "LM Outer", "unit": "psi"},
    {"id": "tire-pressure-lmi", "label": "LM Inner", "unit": "psi"},
    {"id": "tire-pressure-lro", "label": "LR Outer", "unit": "psi"},
    {"id": "tire-pressure-lri", "label": "LR Inner", "unit": "psi"},
    {"id": "tire-pressure-rf", "label": "RF", "unit": "psi"},
    {"id": "tire-pressure-rmo", "label": "RM Outer", "unit": "psi"},
    {"id": "tire-pressure-rmi", "label": "RM Inner", "unit": "psi"},
    {"id": "tire-pressure-rro", "label": "RR Outer", "unit": "psi"},
    {"id": "tire-pressure-rri", "label": "RR Inner", "unit": "psi"},
]

CHAMBER_SIZE_FIELDS = [
    {"id": "chamber-front-left", "label": "Front - Left", "unit": ""},
    {"id": "chamber-front-right", "label": "Front - Right", "unit": ""},
    {"id": "chamber-middle-left", "label": "Middle - Left", "unit": ""},
    {"id": "chamber-middle-right", "label": "Middle - Right", "unit": ""},
    {"id": "chamber-rear-left", "label": "Rear - Left", "unit": ""},
    {"id": "chamber-rear-right", "label": "Rear - Right", "unit": ""},
]

PUSHROD_MEASUREMENT_LAYOUT = [
    ["pushrod-lc", "pushrod-lr", "pushrod-rc", "pushrod-rr"],
]

TREAD_DEPTH_LAYOUT = [
    ["tire-depth-lf", "tire-depth-lmo", "tire-depth-lmi", "tire-depth-lro", "tire-depth-lri"],
    ["tire-depth-rf", "tire-depth-rmo", "tire-depth-rmi", "tire-depth-rro", "tire-depth-rri"],
]

TIRE_PRESSURE_LAYOUT = [
    ["tire-pressure-lf", "tire-pressure-lmo", "tire-pressure-lmi", "tire-pressure-lro", "tire-pressure-lri"],
    ["tire-pressure-rf", "tire-pressure-rmo", "tire-pressure-rmi", "tire-pressure-rro", "tire-pressure-rri"],
]

CHAMBER_SIZE_LAYOUT = [
    ["chamber-front-left", "chamber-front-right"],
    ["chamber-middle-left", "chamber-middle-right"],
    ["chamber-rear-left", "chamber-rear-right"],
]

PUSHROD_MEASUREMENT_MAP = {field["id"]: field for field in PUSHROD_MEASUREMENT_FIELDS}
TREAD_DEPTH_MAP = {field["id"]: field for field in TREAD_DEPTH_FIELDS}
TIRE_PRESSURE_MAP = {field["id"]: field for field in TIRE_PRESSURE_FIELDS}
CHAMBER_SIZE_MAP = {field["id"]: field for field in CHAMBER_SIZE_FIELDS}

TIRE_DEPTH_TO_PRESSURE = {
    field['id']: field['id'].replace('tire-depth', 'tire-pressure') for field in TREAD_DEPTH_FIELDS
}



LEGACY_TREAD_DEPTH_FALLBACKS = {
    "tire-depth-lmo": "tire-depth-lc",
    "tire-depth-lro": "tire-depth-lr",
    "tire-depth-rmo": "tire-depth-rc",
    "tire-depth-rro": "tire-depth-rr",
}

LEGACY_TIRE_PRESSURE_FALLBACKS = {
    "tire-pressure-lmo": "tire-pressure-lc",
    "tire-pressure-lro": "tire-pressure-lr",
    "tire-pressure-rmo": "tire-pressure-rc",
    "tire-pressure-rro": "tire-pressure-rr",
}

DEFAULT_PM_BUSINESS_INFO = {
    'name': (getattr(settings, "DEFAULT_BUSINESS_NAME", "") or "").strip(),
    'address': (getattr(settings, "DEFAULT_BUSINESS_ADDRESS", "") or "").strip(),
    'phone': (getattr(settings, "DEFAULT_BUSINESS_PHONE", "") or "").strip(),
    'email': (getattr(settings, "DEFAULT_BUSINESS_EMAIL", "") or "").strip(),
    'website': (getattr(settings, "SITE_URL", "") or "").strip(),
}


def _to_str(value):
    if value is None:
        return ''
    return str(value).strip()


def _format_date_text(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime('%b %d, %Y')
    return _to_str(value)


def _resolve_customer_name(workorder=None, *, fallback_profile=None):
    """Return the most descriptive customer name available for a work order."""

    workorder = workorder or {}
    fallback_profile = fallback_profile or getattr(getattr(workorder, 'user', None), 'profile', None)

    candidates = [
        getattr(getattr(workorder, 'customer', None), 'name', ''),
        getattr(workorder, 'bill_to', ''),
        getattr(fallback_profile, 'company_name', ''),
    ]

    for value in candidates:
        text_value = _to_str(value)
        if text_value:
            return text_value
    return ''


def _resolve_location(workorder=None, *, fallback_profile=None):
    """Return the best available service location for the work order."""

    workorder = workorder or {}
    vehicle = getattr(workorder, 'vehicle', None)
    fallback_profile = fallback_profile or getattr(getattr(workorder, 'user', None), 'profile', None)

    candidates = [
        getattr(getattr(workorder, 'customer', None), 'address', ''),
        getattr(workorder, 'bill_to_address', ''),
        getattr(vehicle, 'current_location', ''),
        getattr(fallback_profile, 'company_address', ''),
    ]

    for value in candidates:
        text_value = _to_str(value)
        if text_value:
            return text_value
    return ''


def _resolve_mechanic_name(assignment=None):
    """Pick a friendly display name for the assigned mechanic."""

    mechanic = getattr(assignment, 'mechanic', None)
    if not mechanic:
        return ''

    direct_name = _to_str(getattr(mechanic, 'name', ''))
    if direct_name:
        return direct_name

    portal_user = getattr(mechanic, 'portal_user', None)
    if portal_user:
        get_full_name = getattr(portal_user, 'get_full_name', None)
        if callable(get_full_name):
            full_name = _to_str(get_full_name())
            if full_name:
                return full_name
        username = _to_str(getattr(portal_user, 'username', ''))
        if username:
            return username
        email = _to_str(getattr(portal_user, 'email', ''))
        if email:
            return email

    fallback_email = _to_str(getattr(mechanic, 'email', ''))
    if fallback_email:
        return fallback_email

    fallback_phone = _to_str(getattr(mechanic, 'phone', ''))
    if fallback_phone:
        return fallback_phone

    return ''


def _resolve_scheduled_date(workorder=None, *, override=None):
    """Choose the most appropriate scheduled date text for the checklist."""

    candidates = [override, getattr(workorder, 'scheduled_date', None), getattr(workorder, 'date_created', None)]
    for value in candidates:
        formatted = _format_date_text(value)
        if formatted:
            return formatted
    return ''


def _normalize_business_info(profile=None, overrides=None):
    """Merge stored business info with defaults and profile data."""

    info = dict(DEFAULT_PM_BUSINESS_INFO)

    if profile:
        info.update({
            'name': _to_str(getattr(profile, 'company_name', '') or info['name']),
            'address': _to_str(getattr(profile, 'company_address', '') or info['address']),
            'phone': _to_str(getattr(profile, 'company_phone', '') or info['phone']),
            'email': _to_str(getattr(profile, 'company_email', '') or info['email']),
            'website': _to_str(getattr(profile, 'company_website', '') or info['website']),
        })

    overrides = overrides or {}
    for key, value in overrides.items():
        if value:
            info[key] = _to_str(value)

    return info


def _build_vehicle_snapshot(workorder=None, overrides=None):
    vehicle_obj = getattr(workorder, 'vehicle', None)
    base = {
        'unit_number': _to_str(getattr(workorder, 'unit_no', '') or getattr(vehicle_obj, 'unit_number', '')),
        'vin': _to_str(getattr(workorder, 'vehicle_vin', '') or getattr(vehicle_obj, 'vin_number', '')),
        'make_model': _to_str(getattr(workorder, 'make_model', '') or getattr(vehicle_obj, 'make_model', '')),
        'license_plate': _to_str(
            getattr(workorder, 'license_plate', '')
            or getattr(vehicle_obj, 'license_plate', '')
        ),
        'mileage': _to_str(getattr(workorder, 'mileage', '') or getattr(vehicle_obj, 'current_mileage', '')),
        'year': _to_str(getattr(vehicle_obj, 'year', '')),
    }

    overrides = overrides or {}
    for key, value in overrides.items():
        if value not in (None, ''):
            base[key] = _to_str(value)

    return base


def _resolve_checklist_map(checklist):
    resolved = {}
    checklist = checklist or {}
    allowed_statuses = {'pass', 'fail', 'na'}
    for section in PM_CHECKLIST_SECTIONS:
        for item in section['items']:
            entry = checklist.get(item['id'], {})
            status = _to_str(entry.get('status')).lower()
            if status in {'rc', 'ir'}:
                status = 'fail'
            if status not in allowed_statuses:
                status = ''
            resolved[item['id']] = {
                'status': status,
                'notes': _to_str(entry.get('notes')),
            }
    return resolved


def _default_measurements():
    return {
        'pushrod_stroke': {field['id']: '' for field in PUSHROD_MEASUREMENT_FIELDS},
        'tread_depth': {field['id']: '' for field in TREAD_DEPTH_FIELDS},
        'tire_pressure': {field['id']: '' for field in TIRE_PRESSURE_FIELDS},
        'chamber_size': {field['id']: '' for field in CHAMBER_SIZE_FIELDS},
    }


def _resolve_measurements(checklist):
    base = _default_measurements()
    if not isinstance(checklist, dict):
        return base

    measurements = checklist.get('_measurements') or {}
    legacy_maps = {
        'tread_depth': LEGACY_TREAD_DEPTH_FALLBACKS,
        'tire_pressure': LEGACY_TIRE_PRESSURE_FALLBACKS,
    }
    for section_key, template in base.items():
        source = measurements.get(section_key) or {}
        fallback_map = legacy_maps.get(section_key, {})
        for measurement_id in template.keys():
            raw_value = source.get(measurement_id)
            if (raw_value in (None, '') or (isinstance(raw_value, str) and raw_value.strip() == '')) and fallback_map:
                legacy_key = fallback_map.get(measurement_id)
                if legacy_key:
                    raw_value = source.get(legacy_key)
            template[measurement_id] = _to_str(raw_value)
    return base


def _normalize_inspection_date(value, assignment=None):
    """Convert stored inspection date text into a friendly format."""

    raw_text = _to_str(value)
    if raw_text:
        for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y'):
            try:
                parsed = datetime.strptime(raw_text, fmt)
            except ValueError:
                continue
            return _format_date_text(parsed.date())
        return raw_text

    fallback = _format_date_text(getattr(assignment, 'date_assigned', None))
    if fallback:
        return fallback
    return _format_date_text(timezone.localdate())


def _derive_overall_status(inspection):
    """Return a normalized overall status for summary displays."""

    if not inspection:
        return ''

    status = _to_str(getattr(inspection, 'overall_status', '')).lower()
    if status in {'pass', 'fail'}:
        return status

    checklist_map = _resolve_checklist_map(getattr(inspection, 'checklist', {}))
    derived_status = ''
    for entry in checklist_map.values():
        entry_status = entry.get('status')
        if entry_status == 'fail':
            return 'fail'
        if entry_status == 'pass' and derived_status != 'fail':
            derived_status = 'pass'
    return derived_status


def _build_pm_inspection_summary(inspection):
    """Prepare friendly PM inspection metadata for templates."""

    if not inspection:
        return {}

    assignment = getattr(inspection, 'assignment', None)
    inspector_name = _to_str(getattr(inspection, 'inspector_name', ''))
    if not inspector_name:
        inspector_name = _resolve_mechanic_name(assignment)

    inspection_date = _normalize_inspection_date(
        getattr(inspection, 'inspection_date', ''),
        assignment,
    )

    return {
        'inspection_date': inspection_date,
        'inspector_name': inspector_name,
        'overall_status': _derive_overall_status(inspection),
        'submitted_at': getattr(inspection, 'submitted_at', None),
    }


def generate_pm_inspection_pdf(inspection, request, *, blank=False, business_info=None, workorder=None):
    """Render a PM inspection PDF from the stored inspection or defaults."""

    overall_status = ''
    if inspection:
        overall_status = _to_str(getattr(inspection, 'overall_status', '')).lower()
        if overall_status not in {'pass', 'fail'}:
            overall_status = ''

    if inspection:
        workorder = inspection.workorder
        profile = getattr(workorder.user, 'profile', None)
        business_info = _normalize_business_info(profile, inspection.business_snapshot or None)
        vehicle_info = _build_vehicle_snapshot(workorder, inspection.vehicle_snapshot or None)
        checklist_map = _resolve_checklist_map(inspection.checklist)
        measurement_map = _resolve_measurements(inspection.checklist)
        additional_notes = inspection.additional_notes
        assignment = getattr(inspection, 'assignment', None)
        inspector_name = inspection.inspector_name or _resolve_mechanic_name(assignment)
        inspection_date = (
            inspection.inspection_date
            or _format_date_text(getattr(assignment, 'date_assigned', None))
            or _format_date_text(timezone.localdate())
        )
        scheduled_date = inspection.scheduled_date or _resolve_scheduled_date(workorder)
        customer_name = inspection.customer_name or _resolve_customer_name(workorder, fallback_profile=profile)
        location = inspection.location or _resolve_location(workorder, fallback_profile=profile)
    else:
        profile = getattr(getattr(workorder, 'user', None), 'profile', None) if workorder else None
        business_info = _normalize_business_info(profile, business_info)
        vehicle_info = _build_vehicle_snapshot(workorder, getattr(inspection, 'vehicle_snapshot', None) if inspection else None)
        checklist_map = _resolve_checklist_map(getattr(inspection, 'checklist', {}) if inspection else {})
        measurement_map = _resolve_measurements(getattr(inspection, 'checklist', {}) if inspection else {})
        additional_notes = _to_str(getattr(inspection, 'additional_notes', '')) if inspection else ''
        assignments = getattr(workorder, 'assignments', None) if workorder else None
        primary_assignment = assignments.first() if assignments and hasattr(assignments, 'first') else None
        inspector_name = _resolve_mechanic_name(primary_assignment)
        inspection_date = (
            _format_date_text(getattr(primary_assignment, 'date_assigned', None))
            or _format_date_text(timezone.localdate())
        )
        scheduled_date = _resolve_scheduled_date(workorder)
        customer_name = _resolve_customer_name(workorder, fallback_profile=profile)
        location = _resolve_location(workorder, fallback_profile=profile)

    if not overall_status:
        for entry in checklist_map.values():
            status = entry.get('status')
            if status == 'fail':
                overall_status = 'fail'
                break
            if status == 'pass':
                overall_status = 'pass'

    company_logo_url = (
        resolve_company_logo_url(profile, request=request, for_pdf=True)
        if profile else None
    )

    context = {
        'business_info': business_info,
        'workorder': workorder,
        'vehicle_info': vehicle_info,
        'checklist_sections': PM_CHECKLIST_SECTIONS,
        'checklist_map': checklist_map,
        'measurement_map': measurement_map,
        'pushrod_measurement_fields': PUSHROD_MEASUREMENT_FIELDS,
        'tread_depth_fields': TREAD_DEPTH_FIELDS,
        'tire_pressure_fields': TIRE_PRESSURE_FIELDS,
        'chamber_size_fields': CHAMBER_SIZE_FIELDS,
        'pushrod_measurement_layout': PUSHROD_MEASUREMENT_LAYOUT,
        'tread_depth_layout': TREAD_DEPTH_LAYOUT,
        'tire_pressure_layout': TIRE_PRESSURE_LAYOUT,
        'chamber_size_layout': CHAMBER_SIZE_LAYOUT,
        'pushrod_measurement_map': PUSHROD_MEASUREMENT_MAP,
        'tread_depth_map': TREAD_DEPTH_MAP,
        'tire_pressure_map': TIRE_PRESSURE_MAP,
        'tire_pressure_lookup': TIRE_DEPTH_TO_PRESSURE,
        'chamber_size_map': CHAMBER_SIZE_MAP,
        'additional_notes': additional_notes,
        'inspector_name': inspector_name,
        'inspection_date': inspection_date,
        'scheduled_date': scheduled_date,
        'customer_name': customer_name,
        'location': location,
        'mto_header': 'DriveON (MTO) Inspections & Compliance',
        'is_blank': blank and not inspection,
        'overall_status': overall_status,
        'company_logo_url': company_logo_url,
    }

    context = apply_branding_defaults(context)
    html_string = render_to_string('workorders/pm_inspection_pdf.html', context)
    base_url = request.build_absolute_uri('/') if request else None
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not available. PDF generation is disabled. Please install GTK+ libraries for Windows.")
    return HTML(string=html_string, base_url=base_url).write_pdf()


def _build_media_entries(media_files):
    entries = []
    for path in media_files or []:
        if not path:
            continue
        try:
            url = default_storage.url(path)
        except Exception:
            url = path
        entries.append({"path": path, "url": url})
    return entries


def _prepare_assignments(workorder, request=None):
    """Return assignments with portal URLs and collaborator metadata."""
    assignments = list(workorder.assignments.all())
    for assignment in assignments:
        assignment.portal_url = assignment.get_link(request)
        initial = None
        if assignment.rework_instructions:
            initial = {'instructions': assignment.rework_instructions}
        assignment.reassign_form = WorkOrderReassignForm(
            prefix=f"reassign-{assignment.pk}",
            initial=initial,
        )
    for assignment in assignments:
        assignment.collaborators = [
            other for other in assignments if other.pk != assignment.pk
        ]
    workorder.prepared_assignments = assignments
    return assignments


def _handle_timer_action(workorder, action, reason=""):
    """Apply mechanic timer/status transitions mirroring the mobile API."""
    now = timezone.now()
    action = (action or "").strip().lower()
    notify_started = False

    if action == "start":
        if not workorder.mechanic_started_at:
            workorder.mechanic_started_at = now
            notify_started = True
        workorder.mechanic_status = "in_progress"
    elif action == "pause":
        reason = (reason or "").strip()
        travel_reasons = {"travel", "traveling", "traveling to jobsite", "travel to jobsite"}
        if reason.lower() in travel_reasons:
            if not workorder.mechanic_travel_started_at:
                workorder.mechanic_travel_started_at = now
            workorder.mechanic_status = "travel"
        else:
            if not workorder.mechanic_paused_at:
                workorder.mechanic_paused_at = now
                pauses = list(workorder.mechanic_pause_log or [])
                pauses.append({"start": now.isoformat(), "reason": reason})
                workorder.mechanic_pause_log = pauses
            if reason:
                workorder.mechanic_pause_reason = reason[:500]
            workorder.mechanic_status = "paused"
    elif action == "arrived":
        if workorder.mechanic_travel_started_at:
            elapsed = int((now - workorder.mechanic_travel_started_at).total_seconds())
            workorder.mechanic_total_travel_seconds = (
                (workorder.mechanic_total_travel_seconds or 0) + max(elapsed, 0)
            )
            workorder.mechanic_travel_started_at = None
        workorder.mechanic_status = "in_progress"
    elif action == "resume":
        if workorder.mechanic_paused_at:
            elapsed = int((now - workorder.mechanic_paused_at).total_seconds())
            workorder.mechanic_total_paused_seconds = (
                (workorder.mechanic_total_paused_seconds or 0) + max(elapsed, 0)
            )
            pauses = list(workorder.mechanic_pause_log or [])
            if pauses:
                last = pauses[-1]
                if last.get("start") and not last.get("end"):
                    last["end"] = now.isoformat()
                    try:
                        start_dt = datetime.fromisoformat(last["start"]).replace(tzinfo=None)
                        last["seconds"] = int((now.replace(tzinfo=None) - start_dt).total_seconds())
                    except Exception:
                        pass
                    pauses[-1] = last
                    workorder.mechanic_pause_log = pauses
            workorder.mechanic_paused_at = None
        workorder.mechanic_status = "in_progress"
    elif action == "stop":
        if not workorder.mechanic_ended_at:
            workorder.mechanic_ended_at = now
    elif action == "complete":
        missing = []
        if not (workorder.cause and workorder.cause.strip()):
            missing.append("cause")
        if not (workorder.correction and workorder.correction.strip()):
            missing.append("correction")
        if not getattr(workorder, "signature_file", None):
            missing.append("signature")
        if missing:
            return False, {"missing": missing}
        if not workorder.mechanic_ended_at:
            workorder.mechanic_ended_at = now
        workorder.mechanic_marked_complete = True
        workorder.mechanic_completed_at = now
        workorder.mechanic_status = "marked_complete"
    else:
        return False, {"error": "invalid_action"}

    workorder.save(update_fields=[
        "mechanic_started_at",
        "mechanic_paused_at",
        "mechanic_total_paused_seconds",
        "mechanic_travel_started_at",
        "mechanic_total_travel_seconds",
        "mechanic_ended_at",
        "mechanic_pause_reason",
        "mechanic_marked_complete",
        "mechanic_completed_at",
        "mechanic_status",
        "mechanic_pause_log",
    ])
    if notify_started:
        transaction.on_commit(lambda: notify_customer_work_started(workorder))
    return True, {"mechanic_status": workorder.mechanic_status}



@login_required
@activation_required
@subscription_required
def add_workorder(request):
    template_name = 'workorders/workorder_form.html'

    if request.method == 'POST':
        workorder_form = WorkOrderForm(request.POST, user=request.user)
        # Uses the generic formset for manager's initial creation
        formset = WorkOrderRecordFormSet(
            request.POST,
            prefix='workorder_records',
            queryset=WorkOrderRecord.objects.none(),
            form_kwargs={'user': request.user}
        )
        customer_form = CustomerForm(user=request.user) # For modal add
        vehicle_form = VehicleForm()  # For add vehicle modal

        service_entries = parse_service_entries(
            request.POST,
            prefix='workorder_records',
            user=request.user,
        )

        forms_valid = workorder_form.is_valid() and formset.is_valid()
        if forms_valid:
            forms_valid = _validate_completed_line_items(workorder_form, formset)
        if forms_valid:
            try:
                with transaction.atomic():
                    workorder = workorder_form.save(commit=False)
                    workorder.user = request.user

                    customer = workorder_form.cleaned_data.get('customer')
                    if customer:
                        workorder.bill_to = customer.name
                        workorder.bill_to_email = customer.email
                        workorder.bill_to_address = customer.address

                    # If the work order is marked completed on creation we need
                    # to postpone invoice creation until after the records are
                    # saved. Temporarily save with pending status and update
                    # after the formset is processed.
                    final_status = workorder.status
                    create_invoice = final_status == 'completed'
                    if create_invoice:
                        workorder.status = 'pending'

                    # Initial save so we have a PK for the formset
                    workorder.save()
                    logger.info(
                        f"Saved new WorkOrder #{workorder.id}, Status: {workorder.status}"
                    )

                    formset.instance = workorder
                    formset.save()
                    logger.info(
                        f"Saved WorkOrderRecord formset for WorkOrder #{workorder.id}"
                    )

                    if service_entries and workorder.vehicle_id:
                        wo_mileage = workorder_form.cleaned_data.get('mileage')
                        if wo_mileage in (None, '', []):
                            wo_mileage = getattr(workorder.vehicle, 'current_mileage', None)
                        scheduled_date = workorder.scheduled_date or timezone.localdate()
                        source_label = f"Work Order #{workorder.id}"
                        created_tasks = create_maintenance_tasks_from_services(
                            service_entries,
                            vehicle=workorder.vehicle,
                            user=request.user,
                            base_date=scheduled_date,
                            base_mileage=wo_mileage,
                            source_label=source_label,
                            work_order=workorder,
                        )
                        if created_tasks:
                            task_count = len(created_tasks)
                            messages.info(
                                request,
                                f"Added {task_count} maintenance reminder"
                                f"{'s' if task_count != 1 else ''} for {workorder.vehicle}.",
                            )

                    # Now trigger invoice creation if it was originally completed
                    if create_invoice:
                        workorder.status = 'completed'
                        workorder.save()

                    sync_result = sync_workorder_assignments(
                        workorder,
                        workorder_form.selected_mechanics,
                    )
                    for assignment in sync_result['created']:
                        notify_mechanic_assignment(workorder, assignment, request=request)
                        logger.info(
                            "Created assignment %s for WorkOrder #%s",
                            assignment.assignment_token,
                            workorder.id,
                        )

                    messages.success(request, "Work Order created successfully.")
                    return redirect(reverse('accounts:workorder_detail', args=[workorder.pk]))

            except ValidationError as e:
                logger.error(f"Validation error creating work order: {e}")

                message = None
                if hasattr(e, "message_dict"):
                    inventory_errors = e.message_dict.get("inventory")
                    if inventory_errors:
                        if isinstance(inventory_errors, (list, tuple)):
                            message = inventory_errors[0]
                        else:
                            message = inventory_errors
                    else:
                        collected = []
                        for field_errors in e.message_dict.values():
                            if isinstance(field_errors, (list, tuple)):
                                collected.extend(field_errors)
                            else:
                                collected.append(field_errors)
                        if collected:
                            message = "; ".join(str(item) for item in collected if item)
                if not message:
                    message = str(e)

                messages.error(request, message or "Please correct the validation errors below.")
            except Exception as e:
                logger.exception("Unexpected error creating work order:")

                try:
                    connection = transaction.get_connection()
                    if connection.in_atomic_block:
                        connection.set_rollback(True)
                    elif getattr(connection, "needs_rollback", False):
                        connection.rollback()
                except Exception:
                    logger.debug(
                        "Unable to reset transaction state after work order creation error.",
                        exc_info=True,
                    )

                friendly_message = _format_workorder_exception(e)
                messages.error(
                    request,
                    (
                        "An unexpected error occurred while creating the work order: "
                        f"{friendly_message}"
                    ),
                )

        else: # Forms invalid
            logger.warning(f"Work order creation form invalid. WF errors: {workorder_form.errors.as_json()}, FS errors: {formset.errors}")
            messages.error(request, "Please correct the errors below.")

    else: # GET Request
        workorder_form = WorkOrderForm(user=request.user)
        formset = WorkOrderRecordFormSet(
            prefix='workorder_records',
            queryset=WorkOrderRecord.objects.none(),
            form_kwargs={'user': request.user}
        )
        customer_form = CustomerForm(user=request.user)
        vehicle_form = VehicleForm()

    customer_user_ids = get_customer_user_ids(request.user)
    product_user_ids = get_product_user_ids(request.user)
    customers = Customer.objects.filter(user__in=customer_user_ids).order_by('name')
    products = Product.objects.filter(user__in=product_user_ids).order_by('name')
    categories = Category.objects.filter(user__in=product_user_ids).order_by('name')
    product_data = {
        str(product.id): {
            "name": product.name,
            "description": product.description or '',
            "price": str(product.sale_price),
        }
        for product in products
    }
    product_data_json = json.dumps(product_data)
    wo_jobs = (
        WorkOrderRecord.objects.filter(work_order__user=request.user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    )
    ir_jobs = (
        IncomeRecord2.objects.filter(grouped_invoice__user=request.user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    )
    job_catalog, service_description_strings = _build_service_job_catalog(request.user)
    job_suggestions = sorted(set(wo_jobs) | set(ir_jobs) | set(service_description_strings))

    selected_vehicle = _resolve_vehicle_from_form(workorder_form)
    vehicle_history_payload = _serialize_vehicle_history(selected_vehicle)
    vehicle_history_json = json.dumps(vehicle_history_payload)
    vehicle_maintenance_payload = _serialize_vehicle_maintenance(selected_vehicle)
    vehicle_maintenance_json = json.dumps(vehicle_maintenance_payload)
    vehicle_maintenance_payload = _serialize_vehicle_maintenance(selected_vehicle)
    vehicle_maintenance_json = json.dumps(vehicle_maintenance_payload)

    context = {
        'workorder_form': workorder_form,
        'formset': formset,
        'customer_form': customer_form,
        'vehicle_form': vehicle_form,
        'customers': customers,
        'products': products,
        'categories': categories,
        'product_data_json': product_data_json,
        'job_suggestions': job_suggestions,
        'job_catalog_json': job_catalog,
        'documentType': 'workorder',
        'vehicle_history': vehicle_history_payload,
        'vehicle_history_json': vehicle_history_json,
        'vehicle_history_api': reverse('accounts:vehicle_history_summary'),
        'vehicle_maintenance': vehicle_maintenance_payload,
        'vehicle_maintenance_json': vehicle_maintenance_json,
        'vehicle_maintenance_api': reverse('accounts:vehicle_maintenance_summary'),
    }
    return render(request, template_name, context)


@login_required
@require_GET
def vehicle_history_summary(request):
    vehicle_id = request.GET.get('vehicle_id') or request.GET.get('vehicle')
    if not vehicle_id:
        return JsonResponse({'error': 'missing_vehicle'}, status=400)

    try:
        vehicle_id = int(vehicle_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid_vehicle'}, status=400)

    business_user_ids = get_customer_user_ids(request.user)
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, customer__user__in=business_user_ids)
    payload = _serialize_vehicle_history(vehicle)
    return JsonResponse(payload)


@login_required
@require_GET
def vehicle_maintenance_summary(request):
    vehicle_id = request.GET.get('vehicle_id') or request.GET.get('vehicle')
    if not vehicle_id:
        return JsonResponse({'error': 'missing_vehicle'}, status=400)

    try:
        vehicle_id = int(vehicle_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid_vehicle'}, status=400)

    business_user_ids = get_customer_user_ids(request.user)
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, customer__user__in=business_user_ids)
    payload = _serialize_vehicle_maintenance(vehicle)
    return JsonResponse(payload)


def mechanic_workorder_success(request):
    return render(request, 'workorders/mechanic_workorder_submitted.html')


def mechanic_fill_workorder(request, assignment_token):
    """
    Handles the mechanic's view for filling out work order details,
    including labor (jobs) and parts used.
    Accessed via a unique token. Prevents access if already submitted.
    """
    # 1. Get the assignment object or return 404
    assignment = get_object_or_404(WorkOrderAssignment, assignment_token=assignment_token)
    workorder = assignment.workorder
    # Assuming WorkOrder model has a 'user' FK to filter products etc.
    workorder_user = workorder.user

    # 2. Check if this assignment has already been submitted
    if assignment.submitted:
        logger.warning(f"Mechanic attempted to access already submitted WO Assignment for WO #{workorder.id} (Token: {assignment_token})")
        messages.info(request, f"Work Order #{workorder.id} has already been submitted.")
        # Pass context to the "already submitted" template
        context = {
            'workorder': workorder,
            'assignment': assignment # Needed to display submission date
        }
        return render(request, 'workorders/mechanic_workorder_already_submitted.html', context)

    # Allow AJAX actions (timer updates, uploads, quick saves)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax_action')
    if request.method == 'POST' and is_ajax:
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body.decode('utf-8') or '{}')
            except json.JSONDecodeError:
                data = {}
        else:
            data = request.POST.dict()

        ajax_action = data.get('ajax_action') or data.get('action')
        if ajax_action == 'timer':
            timer_action = data.get('timer_action') or data.get('value')
            reason = data.get('reason')
            success, payload = _handle_timer_action(workorder, timer_action, reason)
            status_code = 200 if success else 400
            payload.update({
                'mechanic_status_display': workorder.get_mechanic_status_display(),
                'started_at': workorder.mechanic_started_at.isoformat() if workorder.mechanic_started_at else None,
                'ended_at': workorder.mechanic_ended_at.isoformat() if workorder.mechanic_ended_at else None,
                'paused_at': workorder.mechanic_paused_at.isoformat() if workorder.mechanic_paused_at else None,
                'travel_started_at': workorder.mechanic_travel_started_at.isoformat() if workorder.mechanic_travel_started_at else None,
                'total_paused_seconds': workorder.mechanic_total_paused_seconds,
                'total_travel_seconds': workorder.mechanic_total_travel_seconds,
                'pause_reason': workorder.mechanic_pause_reason,
                'pause_log': workorder.mechanic_pause_log,
            })
            return JsonResponse(payload, status=status_code)

        if ajax_action == 'upload_media':
            upload = request.FILES.get('file')
            if not upload:
                return JsonResponse({'error': 'missing_file'}, status=400)
            timestamp = int(timezone.now().timestamp())
            safe_name = f"order_attachments/job_{workorder.id}_{timestamp}_{getattr(upload, 'name', 'upload')}"
            path = default_storage.save(safe_name, upload)
            media_files = list(workorder.media_files or [])
            media_files.append(path)
            workorder.media_files = media_files
            workorder.save(update_fields=['media_files'])
            entry = _build_media_entries([path])[0]
            return JsonResponse({'ok': True, 'entry': entry})

        if ajax_action == 'remove_media':
            path = data.get('path')
            if not path:
                return JsonResponse({'error': 'missing_path'}, status=400)
            media_files = list(workorder.media_files or [])
            if path in media_files:
                media_files.remove(path)
                workorder.media_files = media_files
                workorder.save(update_fields=['media_files'])
                try:
                    default_storage.delete(path)
                except Exception:
                    pass
            return JsonResponse({'ok': True})

        if ajax_action == 'autocorrect_cause_correction':
            cause_val = str(data.get('cause') or '')
            correction_val = str(data.get('correction') or '')
            corrected_cause = autocorrect_text_block(cause_val)
            corrected_correction = autocorrect_text_block(correction_val)
            return JsonResponse(
                {
                    'ok': True,
                    'cause': corrected_cause,
                    'correction': corrected_correction,
                }
            )

        if ajax_action == 'transcribe_audio':
            upload = request.FILES.get('file')
            target = data.get('target') or data.get('field') or 'cause'
            if not upload:
                return JsonResponse({'ok': False, 'error': 'missing_file'}, status=400)
            try:
                result = transcribe_audio_and_rephrase(upload, target=target)
                return JsonResponse({'ok': True, **result})
            except Exception as exc:
                logger.exception("Transcribe audio failed for work order %s", workorder.id)
                return JsonResponse({'ok': False, 'error': 'transcription_failed', 'message': str(exc)}, status=500)

        if ajax_action == 'save_signature':
            data_url = data.get('data_url') or data.get('dataUrl')
            if not data_url:
                return JsonResponse({'error': 'missing_data'}, status=400)
            try:
                header, encoded = data_url.split(',', 1)
                binary = base64.b64decode(encoded)
            except Exception:
                return JsonResponse({'error': 'invalid_data'}, status=400)
            timestamp = int(timezone.now().timestamp())
            path = f"pods/signature_job_{workorder.id}_{timestamp}.png"
            saved_path = default_storage.save(path, ContentFile(binary))
            workorder.signature_file = saved_path
            workorder.save(update_fields=['signature_file'])
            entry = _build_media_entries([saved_path])[0]
            return JsonResponse({'ok': True, 'signature_url': entry['url']})

        if ajax_action == 'clear_signature':
            if workorder.signature_file:
                workorder.signature_file.delete(save=False)
                workorder.signature_file = None
                workorder.save(update_fields=['signature_file'])
            return JsonResponse({'ok': True})

        if ajax_action == 'update_vehicle':
            vehicle_id_raw = data.get('vehicle_id') or data.get('vehicle')
            if vehicle_id_raw in (None, '', 'null'):
                if workorder.vehicle_id is not None:
                    workorder.vehicle = None
                    workorder.save(update_fields=['vehicle'])
                return JsonResponse({'ok': True, 'vehicle_id': None})

            try:
                vehicle_id = int(vehicle_id_raw)
            except (TypeError, ValueError):
                return JsonResponse({'ok': False, 'error': 'invalid_vehicle'}, status=400)

            try:
                vehicle = Vehicle.objects.get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                return JsonResponse({'ok': False, 'error': 'vehicle_not_found'}, status=404)

            if workorder.vehicle_id != vehicle.id:
                workorder.vehicle = vehicle
                workorder.save(update_fields=['vehicle'])
            return JsonResponse({'ok': True, 'vehicle_id': vehicle.id})

        if ajax_action == 'add_vehicle':
            vehicle_form = VehicleForm(data=request.POST)
            if workorder.customer:
                vehicle_form.instance.customer = workorder.customer
            if vehicle_form.is_valid():
                vehicle = vehicle_form.save(commit=False)
                if workorder.customer:
                    vehicle.customer = workorder.customer
                vehicle.save()
                vehicle_data = {
                    'unit': vehicle.unit_number or '',
                    'vin': vehicle.vin_number or '',
                    'make': vehicle.make_model or '',
                    'mileage': vehicle.current_mileage if vehicle.current_mileage is not None else '',
                }
                parts = [
                    part for part in [vehicle.unit_number, vehicle.make_model, vehicle.vin_number]
                    if part
                ]
                label = " ".join(parts) or f"Vehicle #{vehicle.id}"
                return JsonResponse({'ok': True, 'id': vehicle.id, 'label': label, 'vehicle': vehicle_data})
            return JsonResponse({'ok': False, 'errors': vehicle_form.errors}, status=400)

        return JsonResponse({'error': 'unknown_action'}, status=400)

    # 3. Prepare QuerySets for existing records (only needed if not submitted)
    product_records_queryset = WorkOrderRecord.objects.filter(
        work_order=workorder, product__isnull=False
    ).order_by('id')

    job_records_queryset = WorkOrderRecord.objects.filter(
        work_order=workorder, product__isnull=True
    ).order_by('id')

    # 4. Handle POST request (form submission)
    if request.method == 'POST':
        # Instantiate the main form and the two inline formsets with POST data
        form = MechanicWorkOrderForm(data=request.POST, instance=workorder)
        
        product_formset = MechanicProductUsageRecordInlineFormSet(
            data=request.POST,
            instance=workorder,
            prefix='products', # Must match template
            queryset=product_records_queryset,
            form_kwargs={'user': workorder_user} # Pass user to filter product choices
        )
        vehicle_form = VehicleForm()
        # 4a. Validate all forms and formsets
        is_form_valid = form.is_valid()
        is_product_formset_valid = product_formset.is_valid()

        if is_form_valid and is_product_formset_valid:
            # 4b. Use a database transaction for atomic save
            try:
                with transaction.atomic():
                    logger.info(f"Saving updates for WorkOrder #{workorder.id} from mechanic submission (Token: {assignment_token}).")

                    # Save the main form (updates cause/correction on WorkOrder)
                    workorder_instance = form.save()

                    # Save product line items (handles create/update/delete)
                    product_formset.save()

                    # Check if the mechanic marked it as completed in this submission
                    if form.cleaned_data.get("submitted"):
                        completion_updates = []
                        completion_timestamp = timezone.now()
                        if not workorder_instance.mechanic_marked_complete:
                            workorder_instance.mechanic_marked_complete = True
                            completion_updates.append("mechanic_marked_complete")
                        if not workorder_instance.mechanic_completed_at:
                            workorder_instance.mechanic_completed_at = completion_timestamp
                            completion_updates.append("mechanic_completed_at")
                        if not workorder_instance.mechanic_ended_at:
                            # Treat a submission as a stop timer event when the mechanic forgot to stop it manually.
                            workorder_instance.mechanic_ended_at = completion_timestamp
                            completion_updates.append("mechanic_ended_at")
                        if workorder_instance.mechanic_status != "marked_complete":
                            workorder_instance.mechanic_status = "marked_complete"
                            completion_updates.append("mechanic_status")

                        if completion_updates:
                            workorder_instance.save(update_fields=completion_updates)

                        if not assignment.submitted: # Avoid re-saving if somehow already marked
                            assignment.submitted = True
                            # The WorkOrderAssignment model's save() method now handles setting date_submitted
                            assignment.save()
                            logger.info(f"Assignment for WorkOrder #{workorder.id} marked submitted by mechanic.")
                        else:
                             logger.info(f"Assignment for WorkOrder #{workorder.id} was already submitted when form processed.")
                        # Optionally: Update the WorkOrder status itself if needed
                        # workorder_instance.status = 'some_status_indicating_mechanic_complete'
                        # workorder_instance.save() # Be careful, this triggers WO save logic again

                # 4c. Success: Show message and redirect
                messages.success(request, f"Work Order #{workorder.id} updated successfully.")
                return redirect('accounts:mechanic_workorder_success') # Redirect to generic success page

            except Exception as e:
                # 4d. Handle errors during the save process
                logger.exception(f"Error saving mechanic updates for WorkOrder #{workorder.id} (Token: {assignment_token}):")
                messages.error(request, f"An unexpected error occurred while saving Work Order #{workorder.id}. Please try again or contact support. Error: {e}")
                # Fall through to re-render the form with error messages below

        else:
            # 4e. Handle validation errors
            logger.warning(
                f"Mechanic form validation failed for WO #{workorder.id} (Token: {assignment_token}). Form: {form.errors.as_json()}, Products: {product_formset.errors}"
            )
            # Fall through to re-render the form with invalid data and error messages
            # The form/formset variables already hold the invalid data and errors

    # 5. Handle GET request or POST request with validation errors
    # This part is only reached if the assignment was NOT already submitted
    else: # GET request - instantiate forms for initial display
        form = MechanicWorkOrderForm(instance=workorder) # Populate with existing WO data

        product_formset = MechanicProductUsageRecordInlineFormSet(
            instance=workorder,
            prefix='products',
            queryset=product_records_queryset, # Show existing product lines
            form_kwargs={'user': workorder_user}
        )
        vehicle_form = VehicleForm()

    # Build additional context data for the interactive template
    media_entries = _build_media_entries(workorder.media_files)
    signature_url = None
    if workorder.signature_file:
        try:
            signature_url = _build_media_entries([str(workorder.signature_file)])[0]['url']
        except Exception:
            signature_url = getattr(workorder.signature_file, 'url', str(workorder.signature_file))

    vehicle_options = []
    if workorder.customer:
        vehicles_qs = Vehicle.objects.filter(customer=workorder.customer).order_by('unit_number', 'vin_number')
        for vehicle in vehicles_qs:
            parts = [
                part for part in [vehicle.unit_number, vehicle.make_model, vehicle.vin_number]
                if part
            ]
            label = " ".join(parts) or f"Vehicle #{vehicle.id}"
            vehicle_options.append({
                'id': vehicle.id,
                'label': label,
                'unit': vehicle.unit_number or '',
                'vin': vehicle.vin_number or '',
                'make': vehicle.make_model or '',
                'mileage': vehicle.current_mileage if vehicle.current_mileage is not None else '',
            })

    assignment_list = _prepare_assignments(workorder, request)
    collaborators = [a for a in assignment_list if a.pk != assignment.pk]

    timer_context = {
        'started_at': workorder.mechanic_started_at.isoformat() if workorder.mechanic_started_at else None,
        'ended_at': workorder.mechanic_ended_at.isoformat() if workorder.mechanic_ended_at else None,
        'paused_at': workorder.mechanic_paused_at.isoformat() if workorder.mechanic_paused_at else None,
        'total_paused_seconds': workorder.mechanic_total_paused_seconds or 0,
        'travel_started_at': workorder.mechanic_travel_started_at.isoformat() if workorder.mechanic_travel_started_at else None,
        'total_travel_seconds': workorder.mechanic_total_travel_seconds or 0,
    }

    # 6. Prepare context for rendering the main form template
    job_catalog, service_description_strings = _build_service_job_catalog(workorder_user)
    job_suggestions = sorted(set(
        WorkOrderRecord.objects.filter(work_order__user=workorder_user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    ) | set(
        IncomeRecord2.objects.filter(grouped_invoice__user=workorder_user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    ) | set(service_description_strings))

    context = {
        'form': form,                       # Main form instance
        'product_formset': product_formset, # Formset for products
        'assignment': assignment,           # Current assignment object
        'workorder': workorder,             # Current work order object
        'vehicle_form': vehicle_form,
        'vehicle_options': vehicle_options,
        'media_entries': media_entries,
        'signature_url': signature_url,
        'pause_log': workorder.mechanic_pause_log or [],
        'timer_context': timer_context,
        'mechanic_status': workorder.mechanic_status,
        'mechanic_status_display': workorder.get_mechanic_status_display(),
        'mechanic_status_choices': WorkOrder.MECHANIC_STATUS_CHOICES,
        'assignment_token': assignment.assignment_token,
        'collaborators': collaborators,
        'job_suggestions': job_suggestions,
        'job_catalog_json': job_catalog,
        'requires_rework': assignment.requires_rework,
        'rework_instructions': assignment.rework_instructions,
        'rework_requested_at': assignment.rework_requested_at,
    }
    vehicle_history_payload = _serialize_vehicle_history(workorder.vehicle, mechanic_view=True)
    context.update({
        'vehicle_history': vehicle_history_payload,
        'vehicle_history_json': json.dumps(vehicle_history_payload),
    })
    # Render the template used by the mechanic to fill the form
    return render(request, 'workorders/mechanic_workorder_form.html', context)


def mechanic_pm_checklist(request, assignment_token):
    """Render an interactive PM checklist for mechanics with printable output."""
    assignment = get_object_or_404(WorkOrderAssignment, assignment_token=assignment_token)
    workorder = assignment.workorder

    profile = getattr(workorder.user, 'profile', None)
    inspection = getattr(workorder, 'pm_inspection', None)

    business_info = _normalize_business_info(profile, getattr(inspection, 'business_snapshot', None))
    vehicle_info = _build_vehicle_snapshot(workorder, getattr(inspection, 'vehicle_snapshot', None))

    customer_name = _to_str(getattr(inspection, 'customer_name', '')) or _resolve_customer_name(workorder, fallback_profile=profile)
    location = _to_str(getattr(inspection, 'location', '')) or _resolve_location(workorder, fallback_profile=profile)

    scheduled_date_text = _to_str(getattr(inspection, 'scheduled_date', '')) or _resolve_scheduled_date(workorder)
    inspection_date_text = (
        _to_str(getattr(inspection, 'inspection_date', ''))
        or _format_date_text(getattr(assignment, 'date_assigned', None))
        or _format_date_text(timezone.localdate())
    )
    mechanic_name = _to_str(getattr(inspection, 'inspector_name', '')) or _resolve_mechanic_name(assignment)

    blank = str(request.GET.get('blank', '')).lower() in {'1', 'true', 'yes'}

    inspection_payload = {
        'business_info': business_info,
        'customer_name': customer_name,
        'location': location,
        'scheduled_date': scheduled_date_text,
        'inspection_date': inspection_date_text,
        'inspector_name': mechanic_name,
        'vehicle_info': vehicle_info,
        'checklist': {},
        'measurements': _default_measurements(),
        'additional_notes': '',
        'overall_status': _to_str(getattr(inspection, 'overall_status', '')).lower() if inspection else '',
    }
    if inspection:
        inspection_payload.update({
            'customer_name': inspection.customer_name or customer_name,
            'location': inspection.location or location,
            'scheduled_date': inspection.scheduled_date or scheduled_date_text,
            'inspection_date': inspection.inspection_date or inspection_date_text,
            'inspector_name': inspection.inspector_name or mechanic_name,
            'checklist': inspection.checklist or {},
            'measurements': _resolve_measurements(inspection.checklist),
            'additional_notes': inspection.additional_notes or '',
            'overall_status': _to_str(inspection.overall_status).lower(),
        })

    context = {
        'assignment': assignment,
        'workorder': workorder,
        'checklist_sections': PM_CHECKLIST_SECTIONS,
        'pushrod_measurement_fields': PUSHROD_MEASUREMENT_FIELDS,
        'tread_depth_fields': TREAD_DEPTH_FIELDS,
        'tire_pressure_fields': TIRE_PRESSURE_FIELDS,
        'chamber_size_fields': CHAMBER_SIZE_FIELDS,
        'pushrod_measurement_layout': PUSHROD_MEASUREMENT_LAYOUT,
        'tread_depth_layout': TREAD_DEPTH_LAYOUT,
        'tire_pressure_layout': TIRE_PRESSURE_LAYOUT,
        'chamber_size_layout': CHAMBER_SIZE_LAYOUT,
        'pushrod_measurement_map': PUSHROD_MEASUREMENT_MAP,
        'tread_depth_map': TREAD_DEPTH_MAP,
        'tire_pressure_map': TIRE_PRESSURE_MAP,
        'tire_pressure_lookup': TIRE_DEPTH_TO_PRESSURE,
        'chamber_size_map': CHAMBER_SIZE_MAP,
        'business_info': business_info,
        'vehicle_info': vehicle_info,
        'customer_name': customer_name,
        'location': location,
        'scheduled_date': workorder.scheduled_date,
        'scheduled_date_text': scheduled_date_text,
        'inspection_date_text': inspection_date_text,
        'mechanic_name': mechanic_name,
        'blank': blank,
        'today': timezone.localdate(),
        'inspection': inspection,
        'inspection_json': json.dumps(inspection_payload),
        'overall_status': inspection_payload['overall_status'],
        'save_url': None if blank else reverse('accounts:mechanic_pm_checklist_submit', args=[assignment.assignment_token]),
        'pdf_url': reverse('accounts:mechanic_pm_checklist_pdf', args=[assignment.assignment_token]),
        'blank_pdf_url': reverse('accounts:pm_inspection_blank_pdf'),
    }
    vehicle_history_payload = _serialize_vehicle_history(workorder.vehicle, mechanic_view=True)
    context.update({
        'vehicle_history': vehicle_history_payload,
        'vehicle_history_json': json.dumps(vehicle_history_payload),
    })

    return render(request, 'workorders/mechanic_pm_checklist.html', context)


@csrf_exempt
def mechanic_pm_checklist_submit(request, assignment_token):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    assignment = get_object_or_404(WorkOrderAssignment, assignment_token=assignment_token)
    workorder = assignment.workorder

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    business_info_payload = payload.get('business_info') or {}
    business_snapshot = {}
    for key in DEFAULT_PM_BUSINESS_INFO.keys():
        business_snapshot[key] = _to_str(business_info_payload.get(key))

    vehicle_payload = payload.get('vehicle_info') or {}
    vehicle_snapshot = {}
    for key in ('unit_number', 'vin', 'make_model', 'license_plate', 'mileage', 'year'):
        vehicle_snapshot[key] = _to_str(vehicle_payload.get(key))

    checklist_payload = payload.get('checklist') or {}
    cleaned_checklist = {}
    allowed_statuses = {'pass', 'fail', 'na'}
    for section in PM_CHECKLIST_SECTIONS:
        for item in section['items']:
            entry = checklist_payload.get(item['id'], {})
            status = _to_str(entry.get('status')).lower()
            if status in {'rc', 'ir'}:
                status = 'fail'
            if status not in allowed_statuses:
                status = ''
            cleaned_checklist[item['id']] = {
                'status': status,
                'notes': _to_str(entry.get('notes')),
            }

    measurements_payload = payload.get('measurements') or {}
    cleaned_measurements = _default_measurements()
    for section_key, template in cleaned_measurements.items():
        incoming = measurements_payload.get(section_key) or {}
        for measurement_id in template.keys():
            template[measurement_id] = _to_str(incoming.get(measurement_id))

    cleaned_checklist['_measurements'] = cleaned_measurements

    inspection, created = PMInspection.objects.get_or_create(
        workorder=workorder,
        defaults={'assignment': assignment},
    )
    if not inspection.assignment:
        inspection.assignment = assignment

    inspection.business_snapshot = business_snapshot
    inspection.vehicle_snapshot = vehicle_snapshot
    inspection.checklist = cleaned_checklist
    inspection.additional_notes = _to_str(payload.get('additional_notes'))
    inspection.inspector_name = _to_str(payload.get('inspector_name'))
    inspection.inspection_date = _to_str(payload.get('inspection_date'))
    inspection.scheduled_date = _to_str(payload.get('scheduled_date') or _format_date_text(workorder.scheduled_date))
    inspection.customer_name = _to_str(payload.get('customer_name') or getattr(workorder.customer, 'name', ''))
    inspection.location = _to_str(payload.get('location') or getattr(workorder.customer, 'address', ''))
    overall_status = _to_str(payload.get('overall_status')).lower()
    if overall_status not in {'pass', 'fail'}:
        overall_status = ''
    inspection.overall_status = overall_status
    inspection.submitted_at = timezone.now()
    inspection.save()

    pdf_url = reverse('accounts:mechanic_pm_checklist_pdf', args=[assignment.assignment_token])

    return JsonResponse({
        'status': 'success',
        'message': 'PM inspection saved.',
        'pdf_url': pdf_url,
    })


def mechanic_pm_checklist_pdf(request, assignment_token):
    assignment = get_object_or_404(WorkOrderAssignment, assignment_token=assignment_token)
    inspection = getattr(assignment.workorder, 'pm_inspection', None)
    if not inspection:
        return HttpResponseNotFound('No PM inspection has been submitted for this work order yet.')

    pdf = generate_pm_inspection_pdf(inspection, request)
    filename = f"WorkOrder_{assignment.workorder.id}_PM.pdf"
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def download_pm_inspection_pdf(request, pk):
    workorder = get_object_or_404(WorkOrder, pk=pk, user=request.user)
    inspection = getattr(workorder, 'pm_inspection', None)
    if not inspection:
        return HttpResponseNotFound('No PM inspection has been recorded for this work order yet.')

    pdf = generate_pm_inspection_pdf(inspection, request)
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="WorkOrder_{workorder.id}_PM.pdf"'
    return response


def download_blank_pm_inspection_pdf(request):
    user = request.user if request.user.is_authenticated else None
    profile = getattr(user, 'profile', None) if user else None
    business_info = _normalize_business_info(profile)
    pdf = generate_pm_inspection_pdf(None, request, blank=True, business_info=business_info)
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="PM_Inspection_Blank.pdf"'
    return response


WORKORDER_DATE_RANGE_OPTIONS = [
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("week", "This week"),
    ("month", "This month"),
    ("6m", "Last 6 months"),
    ("year", "This year"),
    ("1y", "Last 12 months"),
    ("all", "All time"),
    ("custom", "Custom range"),
]


def _get_workorder_date_range_bounds(request, default: str = "1y"):
    """
    Parse `?date_range=` and return (key, start_date, end_date).
    - key: one of today/yesterday/week/month/6m/year/1y/all/custom (fallback to default)
    - start_date/end_date: date objects or None
    """

    def _parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    key = ((request.GET.get("date_range") or default) or "").strip().lower()
    valid_keys = {"today", "yesterday", "week", "month", "6m", "year", "1y", "all", "custom"}
    if key not in valid_keys:
        key = default

    today = timezone.localdate()
    start_date = None
    end_date = today

    if key == "today":
        start_date = today
        end_date = today
    elif key == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = start_date
    elif key == "week":
        start_date = today - timedelta(days=today.weekday())
    elif key == "month":
        start_date = today.replace(day=1)
    elif key == "6m":
        start_date = today - relativedelta(months=6)
    elif key == "year":
        start_date = today.replace(month=1, day=1)
    elif key == "1y":
        start_date = today - relativedelta(years=1)
    elif key == "all":
        start_date = None
        end_date = None
    elif key == "custom":
        start_date = _parse_date(request.GET.get("start_date"))
        end_date = _parse_date(request.GET.get("end_date"))
        if start_date and not end_date:
            end_date = start_date
        if end_date and not start_date:
            start_date = end_date

    return key, start_date, end_date


@login_required
def workorder_list(request):
    search_query = (request.GET.get('search') or '').strip()
    date_range_key, start_date, end_date = _get_workorder_date_range_bounds(request, default="1y")

    workorders_qs = (
        WorkOrder.objects
        .filter(user=request.user)
        .select_related('customer', 'vehicle')
        .prefetch_related('assignments__mechanic')
        .order_by('-date_created')
    )

    if start_date:
        workorders_qs = workorders_qs.filter(scheduled_date__isnull=False, scheduled_date__gte=start_date)
    if end_date:
        workorders_qs = workorders_qs.filter(scheduled_date__isnull=False, scheduled_date__lte=end_date)

    if search_query:
        filters = (
            Q(customer__name__icontains=search_query)
            | Q(customer__email__icontains=search_query)
            | Q(unit_no__icontains=search_query)
            | Q(vehicle__unit_number__icontains=search_query)
            | Q(status__icontains=search_query)
        )
        try:
            filters |= Q(id=int(search_query))
        except (TypeError, ValueError):
            pass
        workorders_qs = workorders_qs.filter(filters)

    paginator = Paginator(workorders_qs, 100)
    page_number = request.GET.get('page') or 1
    try:
        workorders_page = paginator.page(page_number)
    except PageNotAnInteger:
        workorders_page = paginator.page(1)
    except EmptyPage:
        workorders_page = paginator.page(paginator.num_pages)

    for workorder in workorders_page:
        _prepare_assignments(workorder, request)

    params = request.GET.copy()
    params.pop('page', None)
    query_string = params.urlencode()

    context = {
        'workorders': workorders_page,
        'paginator': paginator,
        'page_obj': workorders_page,  # keeps template compatibility with page_obj helpers
        'search_query': search_query,
        'date_range_options': WORKORDER_DATE_RANGE_OPTIONS,
        'current_date_range': date_range_key,
        'selected_start_date': start_date,
        'selected_end_date': end_date,
        'query_string': query_string,
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        rows_html = render_to_string('workorders/workorder_rows.html', context, request=request)
        pagination_html = render_to_string('workorders/workorder_pagination.html', context, request=request)
        return JsonResponse(
            {
                'rows_html': rows_html,
                'pagination_html': pagination_html,
                'has_results': bool(workorders_page.object_list),
            }
        )

    return render(request, 'workorders/workorder_list.html', context)


@login_required
def workorder_detail(request, pk):
    workorder = get_object_or_404(
        WorkOrder.objects
        .filter(pk=pk, user=request.user)
        .select_related('customer', 'vehicle', 'invoice')
        .prefetch_related('assignments__mechanic', 'records__product', 'records__driver')
    )
    assignments = _prepare_assignments(workorder, request)
    media_entries = _build_media_entries(workorder.media_files)
    signature_url = None
    if workorder.signature_file:
        try:
            signature_url = _build_media_entries([str(workorder.signature_file)])[0]['url']
        except Exception:
            signature_url = getattr(workorder.signature_file, 'url', str(workorder.signature_file))
    pm_inspection = getattr(workorder, 'pm_inspection', None)
    mechanics = Mechanic.objects.filter(user=request.user).order_by('name')
    quick_job_form = WorkOrderRecordForm(user=request.user)
    wo_jobs = (
        WorkOrderRecord.objects.filter(work_order__user=request.user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    )
    ir_jobs = (
        IncomeRecord2.objects.filter(grouped_invoice__user=request.user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    )
    _job_catalog, service_description_strings = _build_service_job_catalog(request.user)
    job_suggestions = sorted(set(wo_jobs) | set(ir_jobs) | set(service_description_strings))
    job_total = workorder.records.aggregate(total=Sum('amount')).get('total') or Decimal('0')
    job_entries = list(
        workorder.records.select_related('product', 'driver').order_by('date', 'id')
    )
    context = {
        'workorder': workorder,
        'media_entries': media_entries,
        'signature_url': signature_url,
        'assignments': assignments,
        'pm_inspection': pm_inspection,
        'pm_inspection_summary': _build_pm_inspection_summary(pm_inspection),
        'pm_pdf_url': reverse('accounts:workorder_pm_download', args=[workorder.pk]) if pm_inspection else None,
        'pm_blank_pdf_url': reverse('accounts:pm_inspection_blank_pdf'),
        'status_choices': WorkOrder.STATUS_CHOICES,
        'mechanics_options': mechanics,
        'selected_mechanic_ids': [assignment.mechanic_id for assignment in assignments],
        'quick_job_form': quick_job_form,
        'job_suggestions': job_suggestions,
        'job_total': job_total,
        'job_entries': job_entries,
    }
    return render(request, 'workorders/workorder_detail.html', context)


@login_required
@activation_required
@subscription_required
@require_POST
def workorder_quick_update(request, pk):
    workorder = get_object_or_404(
        WorkOrder.objects.select_related('customer'),
        pk=pk,
        user=request.user,
    )

    action = (request.POST.get('action') or '').strip()
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    redirect_url = reverse('accounts:workorder_detail', args=[workorder.pk])
    flash_messages = []

    try:
        if action == 'update_status':
            new_status = (request.POST.get('status') or '').strip()
            valid_statuses = {choice[0] for choice in WorkOrder.STATUS_CHOICES}
            if new_status not in valid_statuses:
                raise ValidationError({'status': 'Please choose a valid status.'})

            if new_status != workorder.status:
                workorder.status = new_status
                workorder.save()
                flash_messages.append(
                    ('success', f"Work Order #{workorder.id} status updated to {workorder.get_status_display()}.")
                )
            else:
                flash_messages.append(
                    ('info', f"Work Order #{workorder.id} is already {workorder.get_status_display().lower()}.")
                )

            payload = {
                'ok': True,
                'status': workorder.status,
                'status_display': workorder.get_status_display(),
                'reload': False,
            }
        elif action == 'update_mechanics':
            raw_ids = request.POST.getlist('mechanics')
            ordered_ids = []
            seen_ids = set()
            for raw in raw_ids:
                try:
                    mechanic_id = int(raw)
                except (TypeError, ValueError):
                    continue
                if mechanic_id in seen_ids:
                    continue
                seen_ids.add(mechanic_id)
                ordered_ids.append(mechanic_id)

            mechanic_lookup = {
                mechanic.pk: mechanic
                for mechanic in Mechanic.objects.filter(user=request.user, pk__in=ordered_ids)
            }
            selected_mechanics = [mechanic_lookup[pk] for pk in ordered_ids if pk in mechanic_lookup]

            sync_result = sync_workorder_assignments(workorder, selected_mechanics)

            for assignment in sync_result['created']:
                try:
                    notify_mechanic_assignment(workorder, assignment, request=request)
                except Exception as exc:
                    logger.warning(
                        "Unable to send mechanic assignment notification for WorkOrder #%s: %s",
                        workorder.id,
                        exc,
                    )

            if sync_result['created']:
                created_names = ', '.join(
                    sorted(
                        filter(None, (getattr(a.mechanic, 'name', None) for a in sync_result['created']))
                    )
                )
                if created_names:
                    flash_messages.append(('success', f"Assigned to {created_names}."))

            if sync_result['removed']:
                removed_names = ', '.join(
                    sorted(filter(None, (entry.get('mechanic_name') for entry in sync_result['removed'])))
                )
                if removed_names:
                    flash_messages.append(('info', f"Removed {removed_names} from this work order."))

            if sync_result['protected']:
                protected_names = ', '.join(
                    sorted(
                        filter(
                            None,
                            (getattr(assignment.mechanic, 'name', None) for assignment in sync_result['protected'])
                        )
                    )
                )
                if protected_names:
                    flash_messages.append(
                        (
                            'warning',
                            f"Kept submitted assignments for {protected_names}."
                        )
                    )

            if not flash_messages:
                flash_messages.append(('info', 'Assignments saved.'))

            assignments_payload = [
                {
                    'id': assignment.pk,
                    'mechanic_id': assignment.mechanic_id,
                    'mechanic_name': getattr(assignment.mechanic, 'name', ''),
                    'submitted': assignment.submitted,
                    'requires_rework': assignment.requires_rework,
                }
                for assignment in workorder.assignments.select_related('mechanic')
            ]

            payload = {
                'ok': True,
                'assignments': assignments_payload,
                'reload': True,
            }
        elif action == 'add_job':
            form = WorkOrderRecordForm(
                data={
                    'job': request.POST.get('job'),
                    'qty': request.POST.get('qty'),
                    'rate': request.POST.get('rate'),
                },
                user=request.user,
            )
            if form.is_valid():
                record = form.save(commit=False)
                record.work_order = workorder
                record.save()
                job_label = record.job or 'New job'
                flash_messages.append(('success', f"Added job '{job_label}'."))
                payload = {
                    'ok': True,
                    'record_id': record.pk,
                    'reload': True,
                }
            else:
                raise ValidationError(form.errors)
        else:
            error_message = 'Unsupported action.'
            if is_ajax:
                return JsonResponse({'ok': False, 'error': error_message}, status=400)
            messages.error(request, error_message)
            return redirect(redirect_url)
    except ValidationError as exc:
        if hasattr(exc, 'message_dict'):
            error_message = ' '.join(
                f"{field}: {' '.join(errors)}" for field, errors in exc.message_dict.items()
            )
        else:
            error_message = ' '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
        if is_ajax:
            return JsonResponse({'ok': False, 'error': error_message}, status=400)
        messages.error(request, error_message)
        return redirect(redirect_url)
    except Exception as exc:
        error_message = _format_workorder_exception(exc)
        if is_ajax:
            return JsonResponse({'ok': False, 'error': error_message}, status=400)
        messages.error(request, error_message)
        return redirect(redirect_url)

    if not is_ajax:
        for level, text in flash_messages:
            if level == 'success':
                messages.success(request, text)
            elif level == 'warning':
                messages.warning(request, text)
            else:
                messages.info(request, text)
        return redirect(redirect_url)

    payload['messages'] = flash_messages
    return JsonResponse(payload)


@login_required
@activation_required
@subscription_required
@require_POST
def workorder_recreate_invoice(request, pk):
    workorder = get_object_or_404(
        WorkOrder.objects.select_related("invoice", "customer"),
        pk=pk,
        user=request.user,
    )

    if workorder.invoice:
        messages.info(
            request,
            f"Invoice {workorder.invoice.invoice_number} is already linked to this work order.",
        )
        return redirect('accounts:workorder_detail', pk=pk)

    if workorder.status != 'completed':
        messages.error(request, "Complete the work order before recreating its invoice.")
        return redirect('accounts:workorder_detail', pk=pk)

    try:
        with transaction.atomic():
            created_invoice = workorder._create_invoice_and_process_inventory()
            if created_invoice:
                WorkOrder.objects.filter(pk=workorder.pk).update(invoice=created_invoice)
                workorder.invoice = created_invoice
                messages.success(
                    request,
                    f"Invoice {created_invoice.invoice_number or created_invoice.id} recreated from this work order.",
                )
            else:
                messages.error(
                    request,
                    "Unable to recreate the invoice for this work order. Please try again.",
                )
    except ValidationError as exc:
        inventory_errors = None
        if hasattr(exc, "message_dict"):
            inventory_errors = exc.message_dict.get("inventory")
        if inventory_errors:
            messages.error(
                request,
                inventory_errors[0] if isinstance(inventory_errors, (list, tuple)) else inventory_errors,
            )
        elif hasattr(exc, "messages") and exc.messages:
            messages.error(request, exc.messages[0])
        else:
            messages.error(request, str(exc))
    except Exception as exc:
        logger.exception("Failed to recreate invoice for WorkOrder #%s", workorder.id)
        friendly = _format_workorder_exception(exc)
        messages.error(request, f"Could not recreate the invoice: {friendly}")

    return redirect('accounts:workorder_detail', pk=pk)


@login_required
@activation_required
@subscription_required
@require_POST
def workorder_assignment_request_rework(request, pk, assignment_id):
    workorder = get_object_or_404(
        WorkOrder.objects.filter(pk=pk, user=request.user)
    )
    assignment = get_object_or_404(
        WorkOrderAssignment.objects.select_related('mechanic', 'workorder'),
        pk=assignment_id,
        workorder=workorder,
    )

    form = WorkOrderReassignForm(request.POST, prefix=f"reassign-{assignment.pk}")

    if not assignment.submitted and not assignment.requires_rework:
        messages.info(
            request,
            f"Work Order #{workorder.id} is already pending with {assignment.mechanic.name}.",
        )
        return redirect('accounts:workorder_detail', pk=workorder.pk)

    if form.is_valid():
        instructions = form.cleaned_data['instructions'].strip()
        assignment.rework_instructions = instructions
        assignment.rework_requested_at = timezone.now()
        assignment.requires_rework = True
        assignment.submitted = False
        assignment.save()

        workorder.mechanic_status = 'in_progress'
        workorder.mechanic_marked_complete = False
        workorder.mechanic_completed_at = None
        WorkOrder.objects.filter(pk=workorder.pk).update(
            mechanic_status='in_progress',
            mechanic_marked_complete=False,
            mechanic_completed_at=None,
        )

        notify_mechanic_rework(workorder, assignment, request=request)
        messages.success(
            request,
            f"Sent Work Order #{workorder.id} back to {assignment.mechanic.name} with updated instructions.",
        )
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)

    return redirect('accounts:workorder_detail', pk=workorder.pk)


@login_required
@activation_required
@subscription_required
def workorder_update(request, pk):
    """
    Manager view to update an existing Work Order.
    Prevents editing if the Work Order status is 'completed', unless the
    requesting user is a superuser.
    """
    template_name = 'workorders/workorder_form.html'
    workorder = get_object_or_404(WorkOrder, pk=pk, user=request.user)

    # --- Check if Work Order is already completed ---
    if workorder.status == 'completed' and not request.user.is_superuser:
        logger.warning(f"User {request.user.username} attempted to edit completed WorkOrder #{pk}.")
        messages.info(request, f"Work Order #{workorder.id} is marked as 'Completed' and cannot be edited directly.")

        invoice_info = None
        invoice_url = None
        if workorder.invoice:
            invoice_info = f"Invoice #{workorder.invoice.invoice_number}"
            try:
                invoice_url = reverse('accounts:groupedinvoice_detail', args=[workorder.invoice.pk])
            except Exception:
                logger.warning(
                    f"Could not reverse URL for groupedinvoice_detail view (PK: {workorder.invoice.pk})",
                    exc_info=False
                )

        return render(request, 'workorders/workorder_completed_cant_edit.html', {
            'workorder': workorder,
            'invoice_info': invoice_info,
            'invoice_url': invoice_url,
        })
    # --- End Check ---

    if (
        request.method == 'POST'
        and (
            request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or request.POST.get('ajax_action')
        )
    ):
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body.decode('utf-8') or '{}')
            except json.JSONDecodeError:
                data = {}
        else:
            data = request.POST.dict()

        ajax_action = data.get('ajax_action') or data.get('action')
        if ajax_action == 'update_vehicle':
            vehicle_id_raw = data.get('vehicle_id') or data.get('vehicle')
            if vehicle_id_raw in (None, '', 'null'):
                if workorder.vehicle_id is not None:
                    workorder.vehicle = None
                    workorder.save(update_fields=['vehicle'])
                return JsonResponse({'ok': True, 'vehicle_id': None})

            try:
                vehicle_id = int(vehicle_id_raw)
            except (TypeError, ValueError):
                return JsonResponse({'ok': False, 'error': 'invalid_vehicle'}, status=400)

            try:
                vehicle = Vehicle.objects.get(pk=vehicle_id)
            except Vehicle.DoesNotExist:
                return JsonResponse({'ok': False, 'error': 'vehicle_not_found'}, status=404)

            if workorder.vehicle_id != vehicle.id:
                workorder.vehicle = vehicle
                workorder.save(update_fields=['vehicle'])
            return JsonResponse({'ok': True, 'vehicle_id': vehicle.id})

    if request.method == 'POST':
        workorder_form = WorkOrderForm(request.POST, instance=workorder, user=request.user)
        formset = WorkOrderRecordFormSet(
            request.POST, instance=workorder, prefix='workorder_records',
            form_kwargs={'user': request.user}
        )

        forms_valid = workorder_form.is_valid() and formset.is_valid()
        if forms_valid:
            forms_valid = _validate_completed_line_items(workorder_form, formset)
        if forms_valid:
            logger.info(f"Update WorkOrder {pk}: Forms valid.")
            try:
                with transaction.atomic():
                    updated_workorder = workorder_form.save(commit=False)

                    # Update bill-to details if customer changed
                    if 'customer' in workorder_form.changed_data:
                        customer = workorder_form.cleaned_data.get('customer')
                        if customer:
                            updated_workorder.bill_to = customer.name
                            updated_workorder.bill_to_email = customer.email
                            updated_workorder.bill_to_address = customer.address
                        else:
                            updated_workorder.bill_to = None
                            updated_workorder.bill_to_email = None
                            updated_workorder.bill_to_address = None

                    # Save and process each WorkOrderRecord BEFORE saving the WorkOrder
                    # This ensures invoice creation (triggered on WorkOrder.save when
                    # status changes to 'completed') includes all latest records.
                    formset.instance = updated_workorder
                    records = formset.save(commit=False)

                    # Build a lookup of form instances keyed by object id so we can
                    # safely match ``formset.save(commit=False)`` results to their
                    # originating forms without relying on ``next(...)`` raising
                    # ``StopIteration`` when Django returns a new instance object.
                    form_lookup = {
                        id(getattr(form, "instance", object())): form
                        for form in formset.forms
                        if getattr(form, "instance", None) is not None
                    }

                    for record in records:
                        # Only handle non-deleted forms
                        if record.pk or not getattr(record, 'DELETE', False):
                            form = form_lookup.get(id(record))
                            if form is None and getattr(record, 'pk', None) is not None:
                                form = next(
                                    (f for f in formset.forms if getattr(f.instance, 'pk', None) == record.pk),
                                    None,
                                )
                            if form is None:
                                logger.warning(
                                    "Update WO %s: Unable to find form for record %s; skipping product sync.",
                                    pk,
                                    getattr(record, 'pk', 'unsaved'),
                                )
                            else:
                                # If product changed, set job & rate
                                if 'product' in getattr(form, 'changed_data', ()): 
                                    prod = form.cleaned_data.get('product')
                                    if prod:
                                        record.job = f"Part – {prod.name}"
                                        record.rate = prod.sale_price
                            record.save()
                            logger.info(
                                f"Update WO {pk}: Saved Record ID {record.pk} - Job: {record.job}, Prod: {record.product_id}"
                            )

                    # Delete any removed records
                    for form in formset.deleted_forms:
                        if form.instance.pk:
                            logger.info(f"Update WO {pk}: Deleting Record ID {form.instance.pk}")
                            form.instance.delete()

                    # Note: assignments handled separately below

                    # Now save the WorkOrder which may trigger invoice creation
                    updated_workorder.save()
                    logger.info(
                        f"Update WorkOrder {pk}: Saved WorkOrder (Status: {updated_workorder.status}).")

                    sync_result = sync_workorder_assignments(
                        updated_workorder,
                        workorder_form.selected_mechanics,
                    )
                    for assignment in sync_result['created']:
                        notify_mechanic_assignment(updated_workorder, assignment, request=request)
                        logger.info(
                            "Created assignment %s for WorkOrder #%s",
                            assignment.assignment_token,
                            updated_workorder.id,
                        )
                    if sync_result['removed']:
                        removed_names = ', '.join(
                            sorted({entry['mechanic_name'] or 'Unknown' for entry in sync_result['removed']})
                        )
                        logger.info(
                            "Removed assignments for mechanics [%s] on WorkOrder #%s",
                            removed_names,
                            updated_workorder.id,
                        )
                    if sync_result['protected']:
                        protected_names = ', '.join(
                            sorted(
                                filter(
                                    None,
                                    [getattr(assignment.mechanic, 'name', '') for assignment in sync_result['protected']]
                                )
                            )
                        )
                        if protected_names:
                            messages.info(
                                request,
                                f"The following mechanics remain assigned because they already submitted their work: {protected_names}.",
                            )

                messages.success(request, "Work Order updated successfully.")
                if 'save_continue' in request.POST:
                    return redirect('accounts:workorder_update', updated_workorder.pk)
                return redirect('accounts:workorder_detail', updated_workorder.pk)

            except ValidationError as e:
                logger.error(f"Validation error updating W O {pk}: {e}")
                inv_err = (e.message_dict.get('inventory') if hasattr(e, 'message_dict')
                           else (e.message if isinstance(e.message, str) else None))
                if inv_err:
                    messages.error(request, inv_err[0] if isinstance(inv_err, list) else inv_err)
                else:
                    messages.error(request, "Please correct the validation errors below.")
            except Exception as e:
                logger.exception(f"Unexpected error updating work order {pk}:")

                # If we are still inside an atomic block mark it for rollback so
                # subsequent queries in this request don't trigger a secondary
                # TransactionManagementError.
                try:
                    connection = transaction.get_connection()
                    if connection.in_atomic_block:
                        connection.set_rollback(True)
                except Exception:
                    # Failing to reset the transaction state should not mask the
                    # original error.
                    logger.debug("Unable to reset transaction state after work order error.", exc_info=True)

                friendly_message = _format_workorder_exception(e)
                messages.error(
                    request,
                    f"An unexpected error occurred while updating the work order: {friendly_message}",
                )
        else:
            logger.warning(
                f"Update WorkOrder {pk}: Invalid data. WF errors: {workorder_form.errors.as_json()}, "
                f"FS errors: {formset.errors}"
            )
            messages.error(request, "Please correct the errors below.")

    else:
        workorder_form = WorkOrderForm(instance=workorder, user=request.user)
        formset = WorkOrderRecordFormSet(
            instance=workorder, prefix='workorder_records',
            form_kwargs={'user': request.user}
        )

    customer_form = CustomerForm(user=request.user)
    customer_user_ids = get_customer_user_ids(request.user)
    product_user_ids = get_product_user_ids(request.user)
    customers = Customer.objects.filter(user__in=customer_user_ids).order_by('name')
    products = Product.objects.filter(user__in=product_user_ids).order_by('name')
    categories = Category.objects.filter(user__in=product_user_ids).order_by('name')
    product_data = {
        str(p.id): {
            "name": p.name,
            "description": p.description or '',
            "price": str(p.sale_price),
        }
        for p in products
    }
    product_data_json = json.dumps(product_data)
    wo_jobs = (
        WorkOrderRecord.objects.filter(work_order__user=request.user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    )
    ir_jobs = (
        IncomeRecord2.objects.filter(grouped_invoice__user=request.user)
        .exclude(job__isnull=True)
        .exclude(job__exact='')
        .values_list('job', flat=True)
    )
    job_catalog, service_description_strings = _build_service_job_catalog(request.user)
    job_suggestions = sorted(set(wo_jobs) | set(ir_jobs) | set(service_description_strings))

    selected_vehicle = _resolve_vehicle_from_form(workorder_form)
    vehicle_history_payload = _serialize_vehicle_history(selected_vehicle)
    vehicle_history_json = json.dumps(vehicle_history_payload)
    vehicle_maintenance_payload = _serialize_vehicle_maintenance(selected_vehicle)
    vehicle_maintenance_json = json.dumps(vehicle_maintenance_payload)

    context = {
        'workorder_form': workorder_form,
        'formset': formset,
        'customer_form': customer_form,
        'customers': customers,
        'products': products,
        'categories': categories,
        'product_data_json': product_data_json,
        'job_suggestions': job_suggestions,
        'job_catalog_json': job_catalog,
        'documentType': 'workorder',
        'workorder': workorder,
        'editing_completed_workorder': workorder.status == 'completed',
        'vehicle_history': vehicle_history_payload,
        'vehicle_history_json': vehicle_history_json,
        'vehicle_history_api': reverse('accounts:vehicle_history_summary'),
        'vehicle_maintenance': vehicle_maintenance_payload,
        'vehicle_maintenance_json': vehicle_maintenance_json,
        'vehicle_maintenance_api': reverse('accounts:vehicle_maintenance_summary'),
    }
    return render(request, template_name, context)




@login_required
def workorder_delete(request, pk):
    workorder = get_object_or_404(WorkOrder, pk=pk, user=request.user)
    if request.method == 'POST':
        workorder_name = str(workorder) # Get identifier before deleting
        workorder.delete()
        messages.success(request, f"{workorder_name} deleted successfully.")
        return redirect(reverse('accounts:workorder_list'))
    return render(request, 'workorders/workorder_confirm_delete.html', {'workorder': workorder})


# ---------------------------
# MECHANIC (EMPLOYEE) VIEWS
# ---------------------------

def _get_mechanic_portal_user(request):
    try:
        return request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return None


def _get_mechanic_employee(mechanic):
    if not mechanic:
        return None
    return Employee.objects.filter(user=mechanic.user, mechanic=mechanic).first()


def _build_mechanic_paystub_context(paystub, request):
    business_user = paystub.payroll_run.user
    profile = getattr(business_user, "profile", None)
    company_logo_url = resolve_company_logo_url(profile, request=request, for_pdf=True) if profile else ""
    timesheet = (
        Timesheet.objects.filter(
            employee=paystub.employee,
            period_start=paystub.payroll_run.period_start,
            period_end=paystub.payroll_run.period_end,
        )
        .prefetch_related("entries")
        .first()
    )
    time_entries = []
    if timesheet:
        time_entries = list(timesheet.entries.all().order_by("work_date", "start_time"))
    context = {
        "paystub": paystub,
        "employee": paystub.employee,
        "payroll_run": paystub.payroll_run,
        "line_items": paystub.line_items.all(),
        "time_entries": time_entries,
        "business_user": business_user,
        "profile": profile,
        "company_logo_url": company_logo_url,
        "generated_on": timezone.localdate(),
        "request": request,
    }
    return apply_branding_defaults(context)


@login_required
def mechanic_list(request):
    mechanics = Mechanic.objects.filter(user=request.user).order_by('name')
    return render(request, 'workorders/mechanic_list.html', {'mechanics': mechanics})


@login_required
def mechanic_detail(request, pk):
    mechanic = get_object_or_404(Mechanic, pk=pk, user=request.user)
    return render(request, 'workorders/mechanic_detail.html', {'mechanic': mechanic})


@login_required
def mechanic_create(request):
    if request.method == 'POST':
        form = MechanicBasicForm(request.POST)
        if form.is_valid():
            mechanic = form.save(commit=False)
            mechanic.user = request.user
            mechanic.save()
            messages.success(request, "Mechanic created successfully.")
            return redirect(reverse('accounts:mechanic_detail', args=[mechanic.pk]))
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = MechanicBasicForm()
    return render(request, 'workorders/mechanic_form.html', {'form': form})


@login_required
def mechanic_update(request, pk):
    mechanic = get_object_or_404(Mechanic, pk=pk, user=request.user)
    if request.method == 'POST':
        form = MechanicForm(request.POST, instance=mechanic)
        if form.is_valid():
            mechanic = form.save(commit=False)
            if form.cleaned_data.get("register_portal"):
                username = form.cleaned_data.get("portal_username")
                password = form.cleaned_data.get("portal_password")
                if username:
                    if mechanic.portal_user:
                        user = mechanic.portal_user
                        user.username = username
                    else:
                        user = User.objects.create_user(username=username)
                        mechanic.portal_user = user
                    if password:
                        user.set_password(password)
                    user.save()
            mechanic.save()
            messages.success(request, "Mechanic updated successfully.")
            return redirect(reverse('accounts:mechanic_detail', args=[mechanic.pk]))
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = MechanicForm(instance=mechanic)
    return render(request, 'workorders/mechanic_form.html', {'form': form})


@login_required
def mechanic_delete(request, pk):
    mechanic = get_object_or_404(Mechanic, pk=pk, user=request.user)
    if request.method == 'POST':
        mechanic_name = mechanic.name
        mechanic.delete()
        messages.success(request, f"Mechanic {mechanic_name} deleted successfully.")
        return redirect(reverse('accounts:mechanic_list'))
    return render(request, 'workorders/mechanic_confirm_delete.html', {'mechanic': mechanic})


@login_required
def mechanic_portal_dashboard(request):
    """Simple dashboard page linking to Jobs and Products."""
    try:
        mechanic = request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return HttpResponseForbidden()
    assignments_qs = (
        WorkOrderAssignment.objects
        .filter(mechanic=mechanic)
        .select_related('workorder', 'workorder__customer')
        .prefetch_related('workorder__assignments__mechanic')
        .order_by('-date_assigned')
    )
    assignments_list = list(assignments_qs)
    for assignment in assignments_list:
        _prepare_assignments(assignment.workorder)
    urgent_assignments = sorted(
        [assignment for assignment in assignments_list if assignment.requires_rework],
        key=lambda a: a.rework_requested_at or a.date_assigned,
        reverse=True,
    )
    def _assignment_sort_key(assignment):
        status_order = {
            'in_progress': 1,
            'pending': 2,
            'completed': 3,
            'cancelled': 4,
        }
        priority = status_order.get(assignment.workorder.status, 9)
        if assignment.requires_rework:
            priority = 0
        recency_source = assignment.rework_requested_at or assignment.date_assigned
        recency_value = recency_source.timestamp() if recency_source else 0
        return (priority, -recency_value)

    sorted_assignments = sorted(assignments_list, key=_assignment_sort_key)
    stats = {
        'total': len(assignments_list),
        'in_progress': sum(1 for a in assignments_list if a.workorder.status == 'in_progress'),
        'completed': sum(1 for a in assignments_list if a.workorder.status == 'completed'),
        'pending': sum(1 for a in assignments_list if a.workorder.status == 'pending'),
        'urgent': len(urgent_assignments),
    }
    context = {
        'mechanic': mechanic,
        'stats': stats,
        'assignments': sorted_assignments,
        'urgent_assignments': urgent_assignments,
    }
    return render(request, 'mechanic/dashboard.html', context)


@login_required
@require_POST
def mechanic_quick_vehicle_workorder(request, task_id):
    try:
        mechanic = request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return HttpResponseForbidden()

    task = get_object_or_404(
        VehicleMaintenanceTask.objects.select_related('vehicle', 'work_order').prefetch_related('work_order__assignments__mechanic'),
        id=task_id,
        vehicle__customer__user=mechanic.user,
    )
    vehicle = task.vehicle

    scheduled_input = (request.POST.get('scheduled_date') or '').strip()
    try:
        scheduled_date = datetime.strptime(scheduled_input, '%Y-%m-%d').date() if scheduled_input else timezone.localdate()
    except ValueError:
        scheduled_date = timezone.localdate()

    description = task.title
    if task.description:
        description = f"{task.title} - {task.description}"[:500]

    if task.work_order_id:
        workorder = task.work_order
        assignments = list(workorder.assignments.all())
        assigned_names = ', '.join(a.mechanic.name for a in assignments) or 'Unassigned'
        if any(a.mechanic_id == mechanic.id for a in assignments):
            messages.info(
                request,
                f"Maintenance task already has Work order #{workorder.id}. You are assigned with: {assigned_names}."
            )
        else:
            messages.info(
                request,
                f"Maintenance task already has Work order #{workorder.id} assigned to {assigned_names}. Use Join Work Order to collaborate."
            )
        return redirect('accounts:mechanic_portal_dashboard')

    try:
        with transaction.atomic():
            workorder = WorkOrder.objects.create(
                user=mechanic.user,
                customer=vehicle.customer,
                vehicle=vehicle,
                scheduled_date=scheduled_date,
                vehicle_vin=vehicle.vin_number,
                mileage=vehicle.current_mileage,
                unit_no=vehicle.unit_number,
                make_model=vehicle.make_model,
                description=description,
                status='pending',
            )
            sync_result = sync_workorder_assignments(workorder, [mechanic])
            for assignment in sync_result['created']:
                notify_mechanic_assignment(workorder, assignment, request=request)
            task.status = VehicleMaintenanceTask.STATUS_IN_PROGRESS
            task.work_order = workorder
            task.save(update_fields=['status', 'work_order', 'updated_at'])
        messages.success(request, f"Work order #{workorder.id} created for {vehicle}.")
    except Exception as exc:
        messages.error(request, f"Unable to create work order: {exc}")

    return redirect('accounts:mechanic_portal_dashboard')


@login_required
@require_POST
def mechanic_join_workorder(request, task_id):
    try:
        mechanic = request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return HttpResponseForbidden()

    task = get_object_or_404(
        VehicleMaintenanceTask.objects.select_related('vehicle', 'work_order').prefetch_related('work_order__assignments__mechanic'),
        id=task_id,
        vehicle__customer__user=mechanic.user,
    )
    workorder = task.work_order
    if not workorder:
        messages.error(request, 'No work order has been created for this maintenance task yet.')
        return redirect('accounts:mechanic_portal_dashboard')

    assignment, created = WorkOrderAssignment.objects.get_or_create(workorder=workorder, mechanic=mechanic)
    if created:
        messages.success(request, f'You joined Work order #{workorder.id}.')
    else:
        messages.info(request, f'You are already assigned to Work order #{workorder.id}.')

    return redirect('accounts:mechanic_portal_dashboard')


@login_required
def mechanic_jobs(request):
    """List work order assignments for the logged in mechanic."""
    try:
        mechanic = request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return HttpResponseForbidden()
    assignments = (
        WorkOrderAssignment.objects
        .filter(mechanic=mechanic)
        .select_related('workorder', 'workorder__customer')
        .prefetch_related('workorder__assignments__mechanic')
        .order_by('-date_assigned')
    )
    assignments = list(assignments)
    for assignment in assignments:
        _prepare_assignments(assignment.workorder)
    return render(request, 'mechanic/jobs.html', {'assignments': assignments})


@login_required
def mechanic_products(request):
    """Display products belonging to the mechanic's business."""
    try:
        mechanic = request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return HttpResponseForbidden()
    products = Product.objects.filter(user=mechanic.user)
    query = request.GET.get('q')
    if query:
        products = products.filter(Q(name__icontains=query) | Q(sku__icontains=query))
    products = products.order_by('name')
    context = {
        'products': products,
    }
    return render(request, 'mechanic/products.html', context)


@login_required
def mechanic_product_update(request, pk):
    """Update location or image for a product from mechanic portal."""
    try:
        mechanic = request.user.mechanic_portal
    except Mechanic.DoesNotExist:
        return HttpResponseForbidden()
    product = get_object_or_404(Product, pk=pk, user=mechanic.user)
    if request.method == 'POST':
        product.location = request.POST.get('location', product.location)
        if 'image' in request.FILES:
            product.image = request.FILES['image']
        product.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
    return redirect('accounts:mechanic_products')


# ---------------------------
# MECHANIC PAYROLL VIEWS
# ---------------------------

@login_required
def mechanic_timesheet_list(request):
    mechanic = _get_mechanic_portal_user(request)
    if not mechanic:
        return HttpResponseForbidden()

    employee = _get_mechanic_employee(mechanic)
    if not employee:
        messages.error(
            request,
            "Your payroll profile is not linked yet. Ask your admin to connect your mechanic profile.",
        )
        return render(request, "mechanic/timesheets.html", {"employee": None})

    settings, _ = PayrollSettings.objects.get_or_create(user=mechanic.user)
    today = timezone.localdate()
    period_start, period_end = get_pay_period_for_date(settings, today)
    current_timesheet = Timesheet.objects.filter(
        employee=employee,
        period_start=period_start,
        period_end=period_end,
    ).first()
    current_total_hours = None
    if current_timesheet:
        current_total_hours = current_timesheet.entries.aggregate(total=Sum("hours")).get("total")

    timesheets = (
        Timesheet.objects.filter(employee=employee)
        .annotate(total_hours=Sum("entries__hours"))
        .order_by("-period_start")
    )

    return render(
        request,
        "mechanic/timesheets.html",
        {
            "employee": employee,
            "timesheets": timesheets,
            "current_timesheet": current_timesheet,
            "current_total_hours": current_total_hours,
            "current_period_start": period_start,
            "current_period_end": period_end,
        },
    )


@login_required
def mechanic_timesheet_current(request):
    mechanic = _get_mechanic_portal_user(request)
    if not mechanic:
        return HttpResponseForbidden()

    employee = _get_mechanic_employee(mechanic)
    if not employee:
        messages.error(
            request,
            "Your payroll profile is not linked yet. Ask your admin to connect your mechanic profile.",
        )
        return redirect("accounts:mechanic_timesheet_list")

    settings, _ = PayrollSettings.objects.get_or_create(user=mechanic.user)
    period_start, period_end = get_pay_period_for_date(settings, timezone.localdate())
    timesheet, _ = Timesheet.objects.get_or_create(
        employee=employee,
        period_start=period_start,
        period_end=period_end,
        defaults={"created_by": request.user},
    )
    return redirect("accounts:mechanic_timesheet_detail", timesheet_id=timesheet.id)


@login_required
def mechanic_timesheet_detail(request, timesheet_id):
    mechanic = _get_mechanic_portal_user(request)
    if not mechanic:
        return HttpResponseForbidden()

    employee = _get_mechanic_employee(mechanic)
    if not employee:
        messages.error(
            request,
            "Your payroll profile is not linked yet. Ask your admin to connect your mechanic profile.",
        )
        return redirect("accounts:mechanic_timesheet_list")

    timesheet = get_object_or_404(Timesheet, id=timesheet_id, employee=employee)
    settings, _ = PayrollSettings.objects.get_or_create(user=mechanic.user)
    has_paystub = PayStub.objects.filter(
        employee=employee,
        payroll_run__period_start=timesheet.period_start,
        payroll_run__period_end=timesheet.period_end,
    ).exists()
    read_only = has_paystub

    posted_values = {}
    errors = []
    saved_entries = 0
    deleted_entries = 0

    if request.method == "POST":
        if read_only:
            messages.error(request, "This timesheet is locked because payroll has already been run.")
        else:
            entry_map = {
                entry.work_date: entry
                for entry in TimeEntry.objects.filter(timesheet=timesheet)
            }
            work_date = timesheet.period_start
            while work_date <= timesheet.period_end:
                key = work_date.strftime("%Y-%m-%d")
                start_raw = (request.POST.get(f"start_time_{key}") or "").strip()
                end_raw = (request.POST.get(f"end_time_{key}") or "").strip()
                notes_raw = (request.POST.get(f"notes_{key}") or "").strip()
                posted_values[work_date] = {
                    "start_time": start_raw,
                    "end_time": end_raw,
                    "notes": notes_raw,
                }

                existing_entry = entry_map.get(work_date)
                if not start_raw and not end_raw and not notes_raw:
                    if existing_entry and (existing_entry.start_time or existing_entry.end_time):
                        existing_entry.delete()
                        deleted_entries += 1
                    elif existing_entry and existing_entry.notes:
                        existing_entry.notes = ""
                        existing_entry.save(update_fields=["notes"])
                    work_date += timedelta(days=1)
                    continue

                if start_raw or end_raw:
                    if not start_raw or not end_raw:
                        errors.append(f"Start and finish times are required for {work_date}.")
                        work_date += timedelta(days=1)
                        continue
                    start_time = parse_time(start_raw)
                    end_time = parse_time(end_raw)
                    if not start_time or not end_time:
                        errors.append(f"Invalid time format for {work_date}.")
                        work_date += timedelta(days=1)
                        continue
                else:
                    start_time = None
                    end_time = None

                if existing_entry:
                    existing_entry.start_time = start_time
                    existing_entry.end_time = end_time
                    existing_entry.notes = notes_raw
                    existing_entry.save()
                else:
                    TimeEntry.objects.create(
                        timesheet=timesheet,
                        work_date=work_date,
                        start_time=start_time,
                        end_time=end_time,
                        notes=notes_raw,
                    )
                saved_entries += 1
                work_date += timedelta(days=1)

            if errors:
                messages.error(request, " ".join(errors))
            else:
                action = request.POST.get("action")
                if settings.auto_approve_timesheets:
                    timesheet.status = Timesheet.STATUS_APPROVED
                    timesheet.approved_at = timezone.now()
                    timesheet.approved_by = mechanic.user
                elif action == "submit" and timesheet.status != Timesheet.STATUS_APPROVED:
                    timesheet.status = Timesheet.STATUS_SUBMITTED
                    timesheet.approved_at = None
                    timesheet.approved_by = None
                if not timesheet.created_by:
                    timesheet.created_by = request.user
                timesheet.save()
                if settings.auto_approve_timesheets or action == "submit":
                    upsert_timesheet_snapshot(
                        timesheet,
                        TimesheetSnapshot.SOURCE_MECHANIC,
                        submitted_by=request.user,
                    )
                messages.success(
                    request,
                    f"Saved {saved_entries} entry(ies). Deleted {deleted_entries} entry(ies).",
                )
                return redirect("accounts:mechanic_timesheet_detail", timesheet_id=timesheet.id)

    entries = TimeEntry.objects.filter(timesheet=timesheet).order_by("work_date")
    entry_map = {entry.work_date: entry for entry in entries}
    rows = []
    work_date = timesheet.period_start
    while work_date <= timesheet.period_end:
        entry = entry_map.get(work_date)
        posted = posted_values.get(work_date, {})
        start_value = posted.get("start_time")
        end_value = posted.get("end_time")
        notes_value = posted.get("notes")

        if start_value is None:
            start_value = entry.start_time.strftime("%H:%M") if entry and entry.start_time else ""
        if end_value is None:
            end_value = entry.end_time.strftime("%H:%M") if entry and entry.end_time else ""
        if notes_value is None:
            notes_value = entry.notes if entry else ""

        rows.append(
            {
                "date": work_date,
                "date_key": work_date.strftime("%Y-%m-%d"),
                "start_value": start_value,
                "end_value": end_value,
                "notes": notes_value,
                "hours": entry.hours if entry else None,
            }
        )
        work_date += timedelta(days=1)

    total_hours = entries.aggregate(total=Sum("hours")).get("total")

    return render(
        request,
        "mechanic/timesheet_detail.html",
        {
            "employee": employee,
            "timesheet": timesheet,
            "rows": rows,
            "total_hours": total_hours,
            "read_only": read_only,
            "auto_approve": settings.auto_approve_timesheets,
        },
    )


@login_required
def mechanic_paystub_list(request):
    mechanic = _get_mechanic_portal_user(request)
    if not mechanic:
        return HttpResponseForbidden()

    employee = _get_mechanic_employee(mechanic)
    if not employee:
        messages.error(
            request,
            "Your payroll profile is not linked yet. Ask your admin to connect your mechanic profile.",
        )
        return render(request, "mechanic/paystubs.html", {"employee": None})

    paystubs = (
        PayStub.objects.filter(employee=employee)
        .select_related("payroll_run")
        .order_by("-payroll_run__period_start")
    )
    return render(
        request,
        "mechanic/paystubs.html",
        {
            "employee": employee,
            "paystubs": paystubs,
        },
    )


@login_required
def mechanic_paystub_detail(request, paystub_id):
    mechanic = _get_mechanic_portal_user(request)
    if not mechanic:
        return HttpResponseForbidden()

    employee = _get_mechanic_employee(mechanic)
    if not employee:
        messages.error(
            request,
            "Your payroll profile is not linked yet. Ask your admin to connect your mechanic profile.",
        )
        return redirect("accounts:mechanic_paystub_list")

    paystub = get_object_or_404(PayStub, id=paystub_id, employee=employee)
    context = _build_mechanic_paystub_context(paystub, request)
    return render(request, "payroll/paystub_pdf.html", context)


@login_required
def mechanic_paystub_download(request, paystub_id):
    mechanic = _get_mechanic_portal_user(request)
    if not mechanic:
        return HttpResponseForbidden()

    employee = _get_mechanic_employee(mechanic)
    if not employee:
        messages.error(
            request,
            "Your payroll profile is not linked yet. Ask your admin to connect your mechanic profile.",
        )
        return redirect("accounts:mechanic_paystub_list")

    paystub = get_object_or_404(PayStub, id=paystub_id, employee=employee)
    context = _build_mechanic_paystub_context(paystub, request)
    try:
        pdf_bytes = render_template_to_pdf("payroll/paystub_pdf.html", context)
    except ImportError as exc:
        messages.error(request, str(exc))
        return redirect("accounts:mechanic_paystub_list")

    employee_label = slugify(paystub.employee.full_name or "employee")
    filename = f"paystub_{employee_label}_{paystub.payroll_run.period_end:%Y%m%d}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def generate_mechanic_signup_code(request):
    """Allow a truck mechanic business to generate a signup code."""
    code = uuid.uuid4().hex[:8]
    MechanicSignupCode.objects.create(business=request.user, code=code)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"code": code})
    return render(request, 'mechanic/signup_code.html', {'code': code})


@login_required
def mechanic_register(request, pk):
    """Register an existing mechanic for portal access."""

    mechanic = get_object_or_404(Mechanic, pk=pk, user=request.user)

    if mechanic.portal_user:
        messages.info(request, "This mechanic already has portal access.")
        return redirect(reverse('accounts:mechanic_detail', args=[pk]))

    if request.method == 'POST':
        form = MechanicSignupForm(request.POST)
        if form.is_valid():
            code_value = form.cleaned_data['signup_code']
            try:
                invite = MechanicSignupCode.objects.get(code=code_value, used=False)
            except MechanicSignupCode.DoesNotExist:
                form.add_error('signup_code', 'Invalid signup code.')
            else:
                user = form.save()
                mechanic.name = form.cleaned_data['name']
                mechanic.phone = form.cleaned_data.get('phone')
                mechanic.email = form.cleaned_data.get('email')
                mechanic.portal_user = user
                mechanic.save()
                invite.used = True
                invite.mechanic = mechanic
                invite.save()
                messages.success(request, "Mechanic registered successfully.")
                return redirect(reverse('accounts:mechanic_detail', args=[pk]))
    else:
        code = uuid.uuid4().hex[:8]
        MechanicSignupCode.objects.create(business=request.user, code=code)
        form = MechanicSignupForm(initial={
            'name': mechanic.name,
            'email': mechanic.email,
            'phone': mechanic.phone,
            'signup_code': code,
        })

    return render(request, 'mechanic/register.html', {
        'form': form,
        'mechanic': mechanic,
    })


def mechanic_signup(request):
    """Signup view for mechanics joining via a code."""
    if request.method == 'POST':
        form = MechanicSignupForm(request.POST)
        if form.is_valid():
            code_value = form.cleaned_data['signup_code']
            try:
                invite = MechanicSignupCode.objects.get(code=code_value, used=False)
            except MechanicSignupCode.DoesNotExist:
                form.add_error('signup_code', 'Invalid signup code.')
            else:
                user = form.save()
                mechanic = Mechanic.objects.create(
                    user=invite.business,
                    name=form.cleaned_data['name'],
                    phone=form.cleaned_data.get('phone'),
                    email=form.cleaned_data.get('email'),
                    portal_user=user,
                )
                invite.used = True
                invite.mechanic = mechanic
                invite.save()
                login(request, user)
                return redirect('accounts:mechanic_portal_dashboard')
    else:
        form = MechanicSignupForm()
    return render(request, 'mechanic/signup.html', {'form': form})

@login_required
def download_workorder_pdf(request, pk):
    """Generate a PDF for a completed work order."""
    workorder = get_object_or_404(WorkOrder, pk=pk, user=request.user)
    if workorder.status != 'completed':
        return HttpResponseForbidden("Work order not completed.")

    profile = request.user.profile
    subtotal = workorder.records.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    company_logo_url = resolve_company_logo_url(profile, request=request, for_pdf=True)
    context = {
        'workorder': workorder,
        'profile': profile,
        'subtotal': subtotal,
        'company_logo_url': company_logo_url,
    }
    context = apply_branding_defaults(context)
    html_string = render_to_string('workorders/workorder_pdf.html', context)
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not available. PDF generation is disabled. Please install GTK+ libraries for Windows.")
    pdf = HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="WorkOrder_{workorder.id}.pdf"'
    return response
