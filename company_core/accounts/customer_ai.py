import json
import logging
import os
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_POST
from openai import OpenAI

from .decorators import customer_login_required
from .models import Payment, VehicleMaintenanceTask, WorkOrder

logger = logging.getLogger(__name__)

BUSINESS_NAME = getattr(settings, "DEFAULT_BUSINESS_NAME", "Truck Zone")

SYSTEM_PROMPT_TEMPLATE = (
    f"You are {BUSINESS_NAME}'s customer-portal assistant. Be concise and action-oriented. "
    "Use only the data provided in the Customer Context. "
    "If the answer is not in context, say you do not have it and point the user to the right portal section "
    "(Invoices, Workorders, Vehicles, Maintenance, Statements, Balances, Shop). "
    "Use the provided portal links list and any item-specific links; format links as Markdown [Label](relative_path) and never include full URLs. "
    "When you mention a vehicle, workorder, invoice, maintenance task, or section, wrap it in a link if a path is provided, and do not show the URL separately from the label. "
    "Never invent information about other customers or internal staff. "
    "Keep sentences short (2-4). Offer next steps when helpful. "
    "Decline legal/medical/sensitive requests. "
    "\n\nPortal links (use these for navigation):\n{links}"
    "\n\nItem links (use these when referencing specific records):\n{item_links}"
    "\n\nCustomer Context:\n{context}"
)

PORTAL_LINKS = [
    "[Dashboard](/account/store/)",
    "[Invoices](/store/invoices/)",
    "[Statements](/store/invoices/statements/)",
    "[Workorders](/store/workorders/)",
    "[Vehicles](/store/vehicles/)",
    "[Maintenance](/store/maintenance/)",
    "[Balances](/store/settlements/)",
    "[Profile](/store/profile/)",
    "[Shop](/store/)",
]


def _serialize_history(raw_history, max_turns=5, max_len=800):
    """Keep the last few turns and trim overly long messages."""
    serialized = []
    if not isinstance(raw_history, list):
        return serialized

    for turn in raw_history[-max_turns:]:
        user_text = str(turn.get("user", "")).strip() if isinstance(turn, dict) else ""
        bot_text = str(turn.get("bot", "")).strip() if isinstance(turn, dict) else ""
        if user_text:
            serialized.append({"role": "user", "content": user_text[:max_len]})
        if bot_text:
            serialized.append({"role": "assistant", "content": bot_text[:max_len]})
    return serialized


def _money(value):
    try:
        amount = Decimal(value or 0)
    except Exception:
        return "$0.00"
    return f"${amount.quantize(Decimal('0.01')):,.2f}"


def _safe_text(value, limit=140):
    return (str(value or "").strip() or "")[:limit]


def _vehicle_label(vehicle):
    parts = []
    unit = getattr(vehicle, "unit_number", "") or ""
    make_model = getattr(vehicle, "make_model", "") or ""
    vin = getattr(vehicle, "vin_number", "") or ""
    if unit:
        parts.append(f"Unit {unit}")
    if make_model:
        parts.append(make_model)
    if vin and not parts:
        parts.append(vin)
    return " - ".join(parts) or "Vehicle"


def _summarize_customer_context(customer_account):
    today = timezone.localdate()

    item_links = []

    invoices_qs = (
        customer_account.invoices.select_related("user")
        .prefetch_related("payments")
        .order_by("-date", "-id")
    )
    invoice_totals = invoices_qs.aggregate(
        total_invoiced=Coalesce(Sum("total_amount"), Decimal("0.00"))
    )
    payment_totals = Payment.objects.filter(invoice__customer=customer_account).aggregate(
        total_paid=Coalesce(Sum("amount"), Decimal("0.00"))
    )
    outstanding_balance = (invoice_totals.get("total_invoiced") or Decimal("0.00")) - (
        payment_totals.get("total_paid") or Decimal("0.00")
    )

    overdue_count = 0
    overdue_total = Decimal("0.00")
    for inv in invoices_qs[:50]:
        try:
            balance_due = inv.balance_due()
        except Exception:
            balance_due = Decimal("0.00")
        due_date = getattr(inv, "due_date", None)
        if balance_due > Decimal("0") and due_date and due_date < today:
            overdue_count += 1
            overdue_total += balance_due

    recent_invoices = []
    for inv in invoices_qs[:5]:
        try:
            balance_due = inv.balance_due()
        except Exception:
            balance_due = Decimal("0.00")
        inv_number = getattr(inv, "invoice_number", inv.id)
        inv_label = f"Invoice #{inv_number}"
        invoice_link = f"/store/invoices/"
        item_links.append(f"{inv_label}: {invoice_link}")
        recent_invoices.append(
            f"[{inv_label}](/store/invoices/) on {getattr(inv, 'date', '')}: "
            f"total {_money(getattr(inv, 'total_amount', 0))}, "
            f"balance {_money(balance_due)}, "
            f"status {getattr(inv, 'payment_status', 'n/a')}, "
            f"due {getattr(inv, 'due_date', '') or 'n/a'}"
        )

    payments_qs = (
        Payment.objects.filter(invoice__customer=customer_account)
        .select_related("invoice")
        .order_by("-date", "-id")[:5]
    )
    recent_payments = []
    for payment in payments_qs:
        invoice = getattr(payment, "invoice", None)
        invoice_label = getattr(invoice, "invoice_number", "") or (invoice.id if invoice else "")
        recent_payments.append(
            f"{getattr(payment, 'date', '')}: { _money(getattr(payment, 'amount', 0)) } "
            f"for invoice #{invoice_label} via {getattr(payment, 'method', 'payment')}"
        )

    workorders_qs = (
        WorkOrder.objects.filter(customer=customer_account)
        .select_related("vehicle")
        .order_by("-date_created", "-id")[:5]
    )
    workorders = []
    for wo in workorders_qs:
        vehicle = getattr(wo, "vehicle", None)
        vehicle_label = _vehicle_label(vehicle) if vehicle else "No vehicle"
        scheduled = getattr(wo, "scheduled_date", None)
        completed = getattr(wo, "completed_date", None)
        item_links.append(f"Workorder {wo.id}: /store/workorders/")
        workorders.append(
            f"[WO {wo.id}](/store/workorders/): {getattr(wo, 'status', '')} for {vehicle_label}; "
            f"scheduled {scheduled or 'n/a'}, completed {completed or 'n/a'}; "
            f"{_safe_text(getattr(wo, 'description', ''), 120)}"
        )

    vehicles_qs = customer_account.vehicles.all().order_by("unit_number", "make_model", "vin_number")[:5]
    vehicles = []
    for vehicle in vehicles_qs:
        label = _vehicle_label(vehicle)
        path = f"/store/vehicles/{vehicle.id}/"
        item_links.append(f"{label}: {path}")
        vehicles.append(f"[{label}]({path}) (VIN {getattr(vehicle, 'vin_number', '') or 'n/a'})")

    active_statuses = VehicleMaintenanceTask.active_statuses()
    maintenance_qs = (
        VehicleMaintenanceTask.objects.filter(vehicle__customer=customer_account, status__in=active_statuses)
        .select_related("vehicle")
        .order_by("due_date", "priority", "title", "pk")[:5]
    )
    maintenance = []
    for task in maintenance_qs:
        vehicle_label = _vehicle_label(getattr(task, "vehicle", None))
        due_parts = []
        if getattr(task, "due_date", None):
            due_parts.append(f"due {task.due_date}")
        if getattr(task, "due_mileage", None):
            due_parts.append(f"at {int(task.due_mileage)} km")
        path = (
            f"/store/vehicles/{task.vehicle_id}/"
            if getattr(task, "vehicle_id", None)
            else "/store/maintenance/"
        )
        item_links.append(f"Task {task.id}: {path}")
        maintenance.append(
            f"[{_safe_text(getattr(task, 'title', 'Maintenance'), 80)}]({path}) ({vehicle_label}) "
            f"{' '.join(due_parts) or 'due date not set'} "
            f"status {getattr(task, 'get_status_display', lambda: getattr(task, 'status', ''))()}"
        )

    profile_summary = [
        _safe_text(getattr(customer_account, "name", ""), 80),
        _safe_text(getattr(customer_account, "email", ""), 80),
        _safe_text(getattr(customer_account, "phone_number", ""), 40),
    ]
    profile_summary = ", ".join([part for part in profile_summary if part])

    sections = [
        f"Customer profile: {profile_summary or 'Not provided'}",
        f"Balances: outstanding={_money(outstanding_balance)}, "
        f"overdue_count={overdue_count}, overdue_total={_money(overdue_total)}",
        "Recent invoices:\n- " + "\n- ".join(recent_invoices) if recent_invoices else "Recent invoices: none",
        "Recent payments:\n- " + "\n- ".join(recent_payments) if recent_payments else "Recent payments: none",
        "Recent workorders:\n- " + "\n- ".join(workorders) if workorders else "Recent workorders: none",
        "Vehicles:\n- " + "\n- ".join(vehicles) if vehicles else "Vehicles: none",
        "Maintenance tasks:\n- " + "\n- ".join(maintenance) if maintenance else "Maintenance tasks: none",
    ]

    item_links_block = "\n".join(sorted(set(item_links)))
    return "\n".join(sections), item_links_block


@require_POST
@customer_login_required
def customer_ai_chat(request):
    """
    Portal-scoped AI endpoint for signed-in customers. Answers using only the
    requesting customer's data.
    """
    get_token(request)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    user_message = (payload.get("message") or "").strip()
    history = payload.get("history") or []

    if not user_message:
        return JsonResponse({"error": "Please enter a question."}, status=400)

    customer_account = getattr(request.user, "customer_portal", None)
    if not customer_account:
        return JsonResponse({"error": "No customer profile found."}, status=403)

    raw_key = getattr(settings, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
    api_key = raw_key.strip() if isinstance(raw_key, str) else None
    if not api_key:
        return JsonResponse({"error": "AI assistant is not configured yet."}, status=503)

    base_url = getattr(settings, "OPENAI_BASE_URL", None) or os.getenv("OPENAI_BASE_URL")
    org = getattr(settings, "OPENAI_ORG", None) or os.getenv("OPENAI_ORG")
    project = getattr(settings, "OPENAI_PROJECT", None) or os.getenv("OPENAI_PROJECT")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url.strip()
    if org:
        client_kwargs["organization"] = org.strip()
    if project:
        client_kwargs["project"] = project.strip()

    model = (
        getattr(settings, "OPENAI_CUSTOMER_MODEL", None)
        or getattr(settings, "OPENAI_PUBLIC_MODEL", None)
        or os.getenv("OPENAI_PUBLIC_MODEL")
        or "gpt-4o-mini"
    ).strip()
    fallback_model = (
        getattr(settings, "OPENAI_CUSTOMER_FALLBACK_MODEL", None)
        or getattr(settings, "OPENAI_PUBLIC_FALLBACK_MODEL", None)
        or os.getenv("OPENAI_PUBLIC_FALLBACK_MODEL")
        or "gpt-4o-mini"
    ).strip()

    client = OpenAI(**client_kwargs)

    context_text, item_links_block = _summarize_customer_context(customer_account)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        context=context_text,
        links="\n".join(PORTAL_LINKS),
        item_links=item_links_block,
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_serialize_history(history))
    messages.append({"role": "user", "content": user_message[:1200]})

    def _run(model_name):
        return client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.35,
            max_tokens=420,
        )

    try:
        completion = _run(model)
    except Exception:
        logger.exception("Customer AI chat failed on model=%s; trying fallback=%s", model, fallback_model)
        if fallback_model and fallback_model != model:
            try:
                completion = _run(fallback_model)
            except Exception:
                logger.exception("Customer AI chat fallback also failed")
                return JsonResponse({"error": "Sorry, I could not get an answer right now."}, status=500)
        else:
            return JsonResponse({"error": "Sorry, I could not get an answer right now."}, status=500)

    reply = completion.choices[0].message.content.strip()
    used_model = getattr(completion, "model", model)

    return JsonResponse({"reply": reply, "model": used_model})
