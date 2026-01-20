from django.utils import timezone
import datetime
# api/views.py
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes, parser_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny

from decimal import Decimal

from django.utils import timezone as dj_tz
from django.contrib.auth import authenticate
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, Count, Prefetch
from django.db.models.functions import Coalesce
from django.conf import settings
from datetime import datetime, time

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.authtoken.models import Token

from accounts.models import (
    Customer, GroupedInvoice, Payment, Note,
    WorkOrder, WorkOrderAssignment, Mechanic, Product, WorkOrderRecord, Vehicle, VehicleMaintenanceTask,
    InventoryTransaction, JobHistory, PMInspection
)
from accounts.utils import notify_mechanic_assignment, sync_workorder_assignments
from .serializers import CustomerSerializer, GroupedInvoiceSerializer, PaymentSerializer, NoteSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = GroupedInvoice.objects.all()
    serializer_class = GroupedInvoiceSerializer


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer


class NoteViewSet(viewsets.ModelViewSet):
    queryset = Note.objects.all()
    serializer_class = NoteSerializer


# ------------------------------
# Mobile mechanics app endpoints
# ------------------------------

def _require_mechanic(request):
    user = request.user

    try:
        return user.mechanic_portal
    except Mechanic.DoesNotExist:
        pass

    # Fall back to auto-linking team accounts that are marked as mechanics.
    profile = getattr(user, "profile", None)
    if not profile:
        return None

    if profile.occupation != "truck_mechanic" or not profile.business_owner:
        return None

    # Check again in case a mechanic exists without the relation cached.
    mechanic = Mechanic.objects.filter(portal_user=user).first()
    if mechanic:
        return mechanic

    # Try to associate an existing mechanic for the same business owner.
    lookup_filters = {"user": profile.business_owner}
    if user.email:
        mechanic = Mechanic.objects.filter(email__iexact=user.email, **lookup_filters).first()
        if mechanic:
            if mechanic.portal_user_id != user.id:
                mechanic.portal_user = user
                if not mechanic.name:
                    mechanic.name = user.get_full_name() or user.username
                if not mechanic.email and user.email:
                    mechanic.email = user.email
                mechanic.save(update_fields=["portal_user", "name", "email"])
            return mechanic

    full_name = user.get_full_name().strip() if callable(getattr(user, "get_full_name", None)) else ""
    if full_name:
        mechanic = Mechanic.objects.filter(name__iexact=full_name, **lookup_filters).first()
        if mechanic:
            if mechanic.portal_user_id != user.id:
                mechanic.portal_user = user
                if not mechanic.email and user.email:
                    mechanic.email = user.email
                mechanic.save(update_fields=["portal_user", "email"])
            return mechanic

    # No existing mechanic found, create one tied to the business owner.
    mechanic = Mechanic.objects.create(
        user=profile.business_owner,
        portal_user=user,
        name=full_name or user.username,
        email=user.email or None,
    )
    return mechanic


def _parse_datetime_param(value: str | None, *, is_end: bool = False):
    if not value:
        return None
    from django.utils.dateparse import parse_datetime, parse_date
    dt = parse_datetime(value)
    if dt is None:
        parsed_date = parse_date(value)
        if parsed_date:
            dt = datetime.combine(parsed_date, time.max if is_end else time.min)
    if dt is None:
        return None
    if dj_tz.is_naive(dt):
        dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
    return dt


def _serialize_timestamp(dt):
    if not dt:
        return None
    if dj_tz.is_naive(dt):
        dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
    return dj_tz.localtime(dt).isoformat()


def _decimal_to_string(value):
    if value is None:
        return "0.00"
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (TypeError, ValueError):
            return "0.00"
    return format(value.quantize(Decimal("0.01")), "f")


def _workorder_to_job_payload(wo: WorkOrder, assignment: WorkOrderAssignment | None = None):
    title = wo.description or f"Work Order #{wo.id}"
    customer_name = getattr(wo.customer, "name", None) or (wo.bill_to or "")
    address = getattr(wo.customer, "address", None) or (wo.bill_to_address or "")
    scheduled = None
    try:
        if wo.scheduled_date:
            scheduled = dj_tz.datetime.combine(wo.scheduled_date, dj_tz.datetime.min.time()).isoformat()
    except Exception:
        scheduled = None
    payload = {
        "id": str(wo.id),
        "title": title,
        "customer_name": customer_name or "",
        "address": address or "",
        "scheduled_at": scheduled,
        "status": wo.status,
    }
    collaborators = []
    for other in wo.assignments.select_related("mechanic"):
        entry = {
            "assignment_id": other.id,
            "mechanic_id": other.mechanic_id,
            "name": getattr(other.mechanic, "name", ""),
            "submitted": other.submitted,
        }
        if assignment and other.pk == assignment.pk:
            payload["assignment"] = {
                "id": other.id,
                "token": other.assignment_token,
                "submitted": other.submitted,
                "timestamps": {
                    "assigned": other.date_assigned.isoformat() if other.date_assigned else None,
                    "submitted": other.date_submitted.isoformat() if other.date_submitted else None,
                },
            }
        else:
            collaborators.append(entry)
    if assignment and "assignment" not in payload:
        payload["assignment"] = {
            "id": assignment.id,
            "token": assignment.assignment_token,
            "submitted": assignment.submitted,
            "timestamps": {
                "assigned": assignment.date_assigned.isoformat() if assignment.date_assigned else None,
                "submitted": assignment.date_submitted.isoformat() if assignment.date_submitted else None,
            },
        }
    payload["collaborators"] = collaborators
    return payload


@api_view(["POST"])
@permission_classes([AllowAny])
def mobile_auth_login(request):
    """Issue a token for portal users (mechanics). Accepts email or username + password.

    Request JSON: { "email": "..." or "username": "...", "password": "..." }
    Response JSON: { "token": "..." }
    """
    body = request.data or {}
    identifier = body.get("email") or body.get("username")
    password = body.get("password")
    if not identifier or not password:
        return Response({"error": "username/email and password required"}, status=400)

    from django.contrib.auth.models import User as DjangoUser

    # Try to find user by username first
    user = None
    try:
        user = DjangoUser.objects.get(username=identifier)
    except DjangoUser.DoesNotExist:
        # Try to find user by email
        try:
            user = DjangoUser.objects.get(email=identifier)
        except DjangoUser.DoesNotExist:
            user = None

    # If user found, check password
    if user and user.check_password(password) and user.is_active:
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key})

    return Response({"error": "invalid_credentials"}, status=400)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_auth_logout(request):
    """Invalidate the current token (best-effort)."""
    try:
        token_key = getattr(request.auth, "key", None) or str(request.auth)
        if token_key:
            Token.objects.filter(key=token_key).delete()
    except Exception:
        pass
    return Response(status=204)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_jobs(request):
    try:
        mechanic = _require_mechanic(request)
        if not mechanic:
            return Response({"error": "not_a_mechanic"}, status=403)

        search = (request.query_params.get("search") or "").strip()
        qs = (
            WorkOrderAssignment.objects
            .filter(mechanic=mechanic)
            .select_related("workorder", "workorder__customer")
            .prefetch_related("workorder__assignments__mechanic")
            .order_by("-date_assigned")
        )
        if search:
            qs = qs.filter(
                Q(workorder__description__icontains=search) |
                Q(workorder__customer__name__icontains=search) |
                Q(workorder__bill_to__icontains=search) |
                Q(workorder__bill_to_address__icontains=search)
            )

        results = []
        for a in qs:
            try:
                results.append(_workorder_to_job_payload(a.workorder, a))
            except Exception as e:
                # Log the error but continue processing other jobs
                print(f"Error processing workorder {a.workorder.id}: {e}")
                continue

        return Response(results)
    except Exception as e:
        print(f"Error in mobile_jobs: {e}")
        import traceback
        traceback.print_exc()
        return Response({"error": "internal_error", "details": str(e)}, status=500)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_vehicle_overview(request):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    active_statuses = VehicleMaintenanceTask.active_statuses()
    vehicles = (
        Vehicle.objects.filter(customer__user=mechanic.user)
        .select_related('customer')
        .annotate(
            upcoming_count=Count('maintenance_tasks', filter=Q(maintenance_tasks__status__in=active_statuses), distinct=True),
            overdue_count=Count(
                'maintenance_tasks',
                filter=Q(maintenance_tasks__status__in=active_statuses, maintenance_tasks__due_date__lt=timezone.localdate()),
                distinct=True,
            ),
            open_workorders=Count(
                'work_orders',
                filter=~Q(work_orders__status='completed'),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                'maintenance_tasks',
                queryset=VehicleMaintenanceTask.objects.filter(status__in=active_statuses).order_by('due_date', 'priority', 'title'),
                to_attr='upcoming_tasks_list',
            ),
            Prefetch(
                'maintenance_tasks',
                queryset=VehicleMaintenanceTask.objects.filter(status=VehicleMaintenanceTask.STATUS_COMPLETED).order_by('-completed_date', '-updated_at')[:3],
                to_attr='recent_completed_tasks',
            ),
        )
        .order_by('customer__name', 'unit_number', 'vin_number')
    )

    payload = []
    for v in vehicles:
        upcoming = []
        for task in getattr(v, 'upcoming_tasks_list', [])[:5]:
            upcoming.append({
                "id": task.id,
                "title": task.title,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "due_mileage": task.due_mileage,
                "mileage_interval": task.mileage_interval,
                "next_due_mileage": task.next_due_mileage,
                "priority": task.priority,
                "status": task.status,
                "is_overdue": task.is_overdue,
                "work_order_id": task.work_order_id,
            })
        recent = []
        for task in getattr(v, 'recent_completed_tasks', []):
            recent.append({
                "id": task.id,
                "title": task.title,
                "completed_date": task.completed_date.isoformat() if task.completed_date else None,
            })
        payload.append({
            "id": v.id,
            "customer": v.customer.name if v.customer else "",
            "vin": v.vin_number,
            "unit_number": v.unit_number,
            "make_model": v.make_model,
            "current_mileage": v.current_mileage,
            "upcoming_count": v.upcoming_count,
            "overdue_count": v.overdue_count,
            "open_workorders": v.open_workorders,
            "upcoming_tasks": upcoming,
            "recent_completed": recent,
        })

    return Response(payload)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_vehicle_create_workorder(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    vehicle = get_object_or_404(Vehicle, pk=pk, customer__user=mechanic.user)
    data = request.data or {}
    scheduled_input = (data.get('scheduled_date') or '').strip()
    try:
        scheduled_date = datetime.date.fromisoformat(scheduled_input) if scheduled_input else timezone.localdate()
    except ValueError:
        scheduled_date = timezone.localdate()

    maintenance_task = None
    task_id = data.get('task_id')
    if task_id:
        try:
            maintenance_task = VehicleMaintenanceTask.objects.get(id=int(task_id), vehicle=vehicle)
        except (VehicleMaintenanceTask.DoesNotExist, ValueError, TypeError):
            maintenance_task = None

    description = maintenance_task.title if maintenance_task else f"Maintenance for {vehicle.make_model or vehicle.vin_number}"
    if maintenance_task and maintenance_task.description:
        description = f"{maintenance_task.title} - {maintenance_task.description}"[:500]

    if maintenance_task and maintenance_task.work_order_id:
        workorder = maintenance_task.work_order
        assignments = list(workorder.assignments.select_related('mechanic'))
        return Response(
            {
                "error": "workorder_exists",
                "message": f"Work order #{workorder.id} is already linked to this maintenance task.",
                "workorder_id": workorder.id,
                "status": workorder.status,
                "assigned_mechanics": [assignment.mechanic.name for assignment in assignments],
            },
            status=409,
        )

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
            if maintenance_task:
                maintenance_task.status = VehicleMaintenanceTask.STATUS_SCHEDULED
                maintenance_task.work_order = workorder
                maintenance_task.save(update_fields=['status', 'work_order', 'updated_at'])
    except Exception as exc:
        return Response({"error": "failed_to_create", "details": str(exc)}, status=400)

    return Response({
        "workorder_id": workorder.id,
        "status": workorder.status,
        "scheduled_date": workorder.scheduled_date.isoformat() if workorder.scheduled_date else None,
        "assigned_mechanics": [assignment.mechanic.name for assignment in workorder.assignments.select_related("mechanic")],
    }, status=201)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_vehicle_history(request, vehicle_id: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    vehicle = get_object_or_404(Vehicle, id=vehicle_id, customer__user=mechanic.user)

    history_qs = (
        vehicle.job_history.exclude(description__iexact="shop supply").exclude(description__iexact="discount")
        .order_by('-job_date', '-id')
        .select_related('invoice', 'source_income_record', 'source_income_record__product')
    )

    jobs: list[dict] = []
    parts: list[dict] = []

    for entry in history_qs[:50]:
        source = getattr(entry, "source_income_record", None)
        product = getattr(source, "product", None)

        if product:
            quantity = getattr(source, "qty", None)
            quantity_display = None
            if quantity is not None:
                if isinstance(quantity, Decimal):
                    quantity_display = format(quantity.normalize())
                else:
                    quantity_display = str(quantity)
            parts.append(
                {
                    "id": entry.id,
                    "jobDate": entry.job_date.isoformat() if entry.job_date else None,
                    "description": product.name or (entry.description or ""),
                    "quantity": quantity_display,
                    "sku": product.sku or None,
                }
            )
            # Skip adding the same entry to the job list to avoid duplicate rows when the
            # invoice line represents a part usage rather than labor.
            continue

        jobs.append(
            {
                "id": entry.id,
                "jobDate": entry.job_date.isoformat() if entry.job_date else None,
                "description": entry.description or "",
                "notes": entry.notes or "",
            }
        )

    payload = {
        "vehicle": {
            "id": vehicle.id,
            "unitNumber": vehicle.unit_number or "",
            "vin": vehicle.vin_number or "",
            "makeModel": vehicle.make_model or "",
            "currentMileage": vehicle.current_mileage,
        },
        "jobs": jobs,
        "parts": parts,
    }

    return Response(payload)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_job_detail(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    try:
        assignment = WorkOrderAssignment.objects.select_related("workorder", "workorder__customer").prefetch_related(
            "workorder__assignments__mechanic"
        ).get(
            mechanic=mechanic, workorder_id=pk
        )
    except WorkOrderAssignment.DoesNotExist:
        return Response({"error": "not_found"}, status=404)

    wo = assignment.workorder
    payload = _workorder_to_job_payload(wo, assignment)
    payload["customer_id"] = getattr(wo.customer, "id", None)
    payload["vehicle_id"] = getattr(wo.vehicle, "id", None)
    payload["cause"] = wo.cause or ""
    payload["correction"] = wo.correction or ""
    payload["vehicle_vin"] = wo.vehicle_vin or ""
    payload["mileage"] = wo.mileage
    payload["unit_no"] = wo.unit_no or ""
    payload["make_model"] = wo.make_model or ""
    
    # Add business information from profile
    default_name = getattr(settings, "DEFAULT_BUSINESS_NAME", "Truck Zone") or "Truck Zone"
    default_address = getattr(settings, "DEFAULT_BUSINESS_ADDRESS", "") or ""
    default_phone = getattr(settings, "DEFAULT_BUSINESS_PHONE", "") or ""
    default_email = getattr(settings, "DEFAULT_BUSINESS_EMAIL", "") or ""
    default_website = getattr(settings, "SITE_URL", "") or ""
    profile = getattr(wo.user, 'profile', None)
    if profile:
        payload["business_name"] = getattr(profile, 'company_name', '') or default_name
        payload["business_address"] = getattr(profile, 'company_address', '') or default_address
        payload["business_phone"] = getattr(profile, 'company_phone', '') or default_phone
        payload["business_email"] = getattr(profile, 'company_email', '') or default_email
        payload["business_website"] = getattr(profile, 'company_website', '') or default_website
    else:
        payload["business_name"] = default_name
        payload["business_address"] = default_address
        payload["business_phone"] = default_phone
        payload["business_email"] = default_email
        payload["business_website"] = default_website
    
    payload["has_signature"] = bool(getattr(wo, "signature_file", None))
    _sig = getattr(wo, "signature_file", None)
    try:
        payload["signature_file"] = _sig.url if _sig and hasattr(_sig, "url") else (str(_sig) if _sig else None)
    except Exception:
        payload["signature_file"] = str(_sig) if _sig else None
    payload["media_files"] = list(wo.media_files or [])
    payload["description"] = wo.description or ""
    payload["mechanic_started_at"] = wo.mechanic_started_at.isoformat() if wo.mechanic_started_at else None
    payload["mechanic_ended_at"] = wo.mechanic_ended_at.isoformat() if wo.mechanic_ended_at else None
    payload["mechanic_paused_at"] = wo.mechanic_paused_at.isoformat() if wo.mechanic_paused_at else None
    payload["mechanic_total_paused_seconds"] = wo.mechanic_total_paused_seconds or 0
    payload["mechanic_pause_reason"] = wo.mechanic_pause_reason or ""
    payload["mechanic_status"] = getattr(wo, "mechanic_status", "not_started")
    payload["mechanic_travel_started_at"] = wo.mechanic_travel_started_at.isoformat() if getattr(wo, "mechanic_travel_started_at", None) else None
    payload["mechanic_total_travel_seconds"] = getattr(wo, "mechanic_total_travel_seconds", 0) or 0
    payload["mechanic_pause_log"] = list(getattr(wo, "mechanic_pause_log", []) or [])
    payload["mechanic_marked_complete"] = bool(getattr(wo, "mechanic_marked_complete", False))
    payload["mechanic_completed_at"] = wo.mechanic_completed_at.isoformat() if getattr(wo, "mechanic_completed_at", None) else None
    payload["is_read_only"] = bool(getattr(wo, "mechanic_marked_complete", False)) or (wo.status == "completed" and bool(wo.completed_at))
    notes_parts = [p for p in [wo.description, wo.cause, wo.correction] if p]
    if notes_parts:
        payload["notes"] = "\n\n".join(notes_parts)
    return Response(payload)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_job_set_status(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    try:
        assignment = WorkOrderAssignment.objects.select_related("workorder").get(mechanic=mechanic, workorder_id=pk)
    except WorkOrderAssignment.DoesNotExist:
        return Response({"error": "not_found"}, status=404)

    body = request.data or {}
    incoming = (body.get("status") or "").strip()
    if not incoming:
        return Response({"error": "missing_status"}, status=400)

    new_status = incoming
    valid_statuses = {s for (s, _label) in getattr(WorkOrder, "STATUS_CHOICES", [])}
    if not new_status or new_status not in valid_statuses:
        return Response({"error": "invalid_status", "allowed": sorted(list(valid_statuses))}, status=400)
    if new_status == "completed":
        return Response({"error": "forbidden", "detail": "Mechanics cannot mark a work order as completed."}, status=403)

    wo = assignment.workorder
    now = dj_tz.now()
    if new_status == "in_progress" and not wo.mechanic_started_at:
        wo.mechanic_started_at = now
    if wo.status != new_status:
        wo.status = new_status
    wo.save(update_fields=["status", "mechanic_started_at"]) 

    return Response({"ok": True, "status": wo.status})


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def mobile_job_upload_attachment(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    if not WorkOrderAssignment.objects.filter(mechanic=mechanic, workorder_id=pk).exists():
        return Response({"error": "not_found"}, status=404)

    f = request.FILES.get("file")
    if not f:
        return Response({"error": "missing_file"}, status=400)

    timestamp = int(dj_tz.now().timestamp())
    safe_name = f"order_attachments/job_{pk}_{timestamp}_{getattr(f, 'name', 'upload')}"
    path = default_storage.save(safe_name, f)

    try:
        wo = WorkOrder.objects.get(id=pk)
        media_files = list(wo.media_files or [])
        media_files.append(path)
        wo.media_files = media_files
        wo.save(update_fields=['media_files'])
    except WorkOrder.DoesNotExist:
        pass

    return Response({"uploaded": True, "path": path}, status=201)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_job_signature(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    if not WorkOrderAssignment.objects.filter(mechanic=mechanic, workorder_id=pk).exists():
        return Response({"error": "not_found"}, status=404)

    data_url = (request.data or {}).get("dataUrl") or ""
    try:
        header, b64data = data_url.split(",", 1)
    except ValueError:
        return Response({"error": "invalid_data_url"}, status=400)
    import base64
    try:
        binary = base64.b64decode(b64data)
    except Exception:
        return Response({"error": "invalid_base64"}, status=400)

    timestamp = int(dj_tz.now().timestamp())
    path = default_storage.save(f"pods/signature_job_{pk}_{timestamp}.png", ContentFile(binary))
    try:
        wo = WorkOrder.objects.get(id=pk)
        wo.signature_file = path
        wo.save(update_fields=["signature_file"])
    except WorkOrder.DoesNotExist:
        pass
    return Response({"saved": True, "path": path}, status=201)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_job_add_part(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    try:
        wo = WorkOrder.objects.get(id=pk)
    except WorkOrder.DoesNotExist:
        return Response({"error": "not_found"}, status=404)
    if not WorkOrderAssignment.objects.filter(mechanic=mechanic, workorder=wo).exists():
        return Response({"error": "not_assigned"}, status=403)

    body = request.data or {}
    part_id = body.get("partId")
    qty = body.get("quantity") or 1
    try:
        product = Product.objects.get(id=int(part_id), user=mechanic.user)
    except Exception:
        return Response({"error": "invalid_part"}, status=400)

    try:
        rec = (
            WorkOrderRecord.objects
            .filter(work_order=wo, product=product)
            .order_by('id')
            .first()
        )
        if rec:
            rec.qty = (rec.qty or 0) + int(qty or 1)
            rec.rate = product.sale_price
            rec.save(update_fields=["qty", "rate"])
        else:
            rec = WorkOrderRecord.objects.create(
                work_order=wo,
                product=product,
                job=f"Part – {product.name}",
                qty=qty,
                rate=product.sale_price,
                date=dj_tz.now().date(),
            )
    except Exception as e:
        return Response({"error": str(e)}, status=400)
    return Response({"ok": True, "record_id": rec.id, "qty": rec.qty})


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_job_remove_part(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    try:
        wo = WorkOrder.objects.get(id=pk)
    except WorkOrder.DoesNotExist:
        return Response({"error": "not_found"}, status=404)
    if not WorkOrderAssignment.objects.filter(mechanic=mechanic, workorder=wo).exists():
        return Response({"error": "not_assigned"}, status=403)

    body = request.data or {}
    part_id = body.get("partId")
    clear = bool(body.get("clear"))
    if not part_id:
        return Response({"error": "part_required"}, status=400)

    try:
        rec = WorkOrderRecord.objects.filter(work_order=wo, product_id=int(part_id)).order_by('id').first()
        if not rec:
            return Response({"error": "not_found"}, status=404)
        if clear:
            # Delete the record completely instead of setting qty to 0
            rec.delete()
            return Response({"ok": True, "qty": 0, "deleted": True})
        else:
            rec.qty = max(0, (rec.qty or 0) - 1)
            # If quantity reaches 0, delete the record
            if rec.qty == 0:
                rec.delete()
                return Response({"ok": True, "qty": 0, "deleted": True})
            else:
                rec.save(update_fields=["qty"])
                return Response({"ok": True, "qty": rec.qty})
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_parts_search(request):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    search = (request.query_params.get("search") or "").strip()
    products = Product.objects.filter(user=mechanic.user)
    if search:
        products = products.filter(Q(name__icontains=search) | Q(sku__icontains=search))
    products = products.order_by("name")[:100]
    data = [{"id": str(p.id), "name": p.name, "sku": p.sku} for p in products]
    return Response(data)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_mechanic_summary(request):
    try:
        mechanic = _require_mechanic(request)
        if not mechanic:
            return Response({"error": "not_a_mechanic"}, status=403)

        assignments_qs = (
            WorkOrderAssignment.objects
            .filter(mechanic=mechanic)
            .select_related("workorder", "workorder__customer")
            .prefetch_related("workorder__assignments__mechanic")
        )

        total_assigned_count = assignments_qs.count()
        in_progress_count = assignments_qs.filter(workorder__status='in_progress').count()
        completed_count = assignments_qs.filter(workorder__status='completed').count()
        pending_count = assignments_qs.filter(workorder__status='pending').count()

        try:
            low_stock_count = Product.get_low_stock_products(mechanic.user).count()
        except Exception:
            low_stock_count = 0

        recent_assignments = list(
            assignments_qs.order_by('-date_assigned')[:5]
        )
        maintenance_qs = VehicleMaintenanceTask.objects.filter(
            vehicle__customer__user=mechanic.user,
            status__in=VehicleMaintenanceTask.active_statuses(),
        )
        maintenance_due_count = maintenance_qs.count()
        maintenance_overdue_count = maintenance_qs.filter(due_date__lt=timezone.localdate()).count()
        recent = []
        for a in recent_assignments:
            try:
                wo = a.workorder
                team = [
                    {
                        "assignment_id": teammate.id,
                        "name": getattr(teammate.mechanic, "name", ""),
                        "submitted": teammate.submitted,
                    }
                    for teammate in wo.assignments.all()
                    if teammate.pk != a.pk
                ]
                recent.append({
                    "id": wo.id,
                    "title": wo.description or f"Work Order #{wo.id}",
                    "customer": getattr(wo.customer, 'name', None) or (wo.bill_to or ''),
                    "status": wo.status,
                    "date_assigned": a.date_assigned.isoformat() if a.date_assigned else None,
                    "team": team,
                })
            except Exception as e:
                print(f"Error processing recent assignment {a.id}: {e}")
                continue

        return Response({
            "stats": {
                "total": total_assigned_count,
                "in_progress": in_progress_count,
                "completed": completed_count,
                "pending": pending_count,
                "low_stock": low_stock_count,
                "maintenance_due": maintenance_due_count,
                "maintenance_overdue": maintenance_overdue_count,
            },
            "recent": recent,
            "mechanic": {
                "name": mechanic.name,
            }
        })
    except Exception as e:
        print(f"Error in mobile_mechanic_summary: {e}")
        import traceback
        traceback.print_exc()
        return Response({"error": "internal_error", "details": str(e)}, status=500)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_activity_history(request):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    search_term = (request.query_params.get("search") or "").strip().lower()
    type_filter = (request.query_params.get("type") or "").strip().lower()
    limit = max(1, min(int(request.query_params.get("limit", 50)), 200))
    offset = max(0, int(request.query_params.get("offset", 0)))

    user_filter_values = []
    for key in ("users", "user", "users[]"):
        user_filter_values.extend(request.query_params.getlist(key))
    if not user_filter_values and request.query_params.get("users"):
        user_filter_values = [v.strip() for v in request.query_params.get("users", "").split(",") if v.strip()]
    normalized_user_filters = [value.strip().lower() for value in user_filter_values if value.strip()]

    start_at = _parse_datetime_param(request.query_params.get("start"))
    end_at = _parse_datetime_param(request.query_params.get("end"), is_end=True)

    activities = []
    available_users = set()

    assignments_qs = (
        WorkOrderAssignment.objects
        .filter(mechanic=mechanic)
        .select_related("workorder", "workorder__customer")
        .prefetch_related("workorder__assignments__mechanic")
        .order_by("-date_assigned")
    )
    if start_at:
        assignments_qs = assignments_qs.filter(date_assigned__gte=start_at)
    if end_at:
        assignments_qs = assignments_qs.filter(date_assigned__lte=end_at)

    for assignment in assignments_qs[:250]:
        workorder = assignment.workorder
        timestamp = assignment.date_assigned or workorder.updated_at or workorder.created_at
        team = []
        for teammate in workorder.assignments.all():
            name = getattr(teammate.mechanic, "name", "").strip()
            if name:
                team.append(name)
                available_users.add(name)
        if mechanic.name:
            available_users.add(mechanic.name)
        description_parts = [getattr(workorder.customer, "name", None) or workorder.bill_to or "Unknown customer"]
        if workorder.status:
            description_parts.append(f"Status: {workorder.status.replace('_', ' ').title()}")
        activities.append({
            "id": f"workorder-{workorder.id}-{assignment.id}",
            "type": "workorder",
            "title": workorder.description or f"Work Order #{workorder.id}",
            "description": ", ".join(description_parts),
            "status": workorder.status,
            "timestamp": _serialize_timestamp(timestamp),
            "users": team or ([mechanic.name] if mechanic.name else []),
            "context": {
                "workorder_id": workorder.id,
                "customer": getattr(workorder.customer, "name", None) or workorder.bill_to,
            },
        })

    invoices_qs = (
        GroupedInvoice.objects
        .filter(user=mechanic.user)
        .select_related("customer")
        .order_by("-updated_at")
    )
    if start_at:
        invoices_qs = invoices_qs.filter(updated_at__gte=start_at)
    if end_at:
        invoices_qs = invoices_qs.filter(updated_at__lte=end_at)

    for invoice in invoices_qs[:200]:
        timestamp = invoice.updated_at or invoice.created_at
        title = invoice.invoice_number or f"Invoice #{invoice.id}"
        customer_name = getattr(invoice.customer, "name", None) or invoice.bill_to or "Unassigned customer"
        full_name = mechanic.user.get_full_name() or mechanic.user.get_username()
        available_users.add(full_name)
        activities.append({
            "id": f"invoice-{invoice.id}",
            "type": "invoice",
            "title": title,
            "description": f"{customer_name} • Total {invoice.total_amount}",
            "status": invoice.payment_status,
            "timestamp": _serialize_timestamp(timestamp),
            "users": [full_name],
            "context": {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "customer": customer_name,
            },
        })

    inventory_qs = (
        InventoryTransaction.objects
        .filter(user=mechanic.user)
        .select_related("product")
        .order_by("-transaction_date")
    )
    if start_at:
        inventory_qs = inventory_qs.filter(transaction_date__gte=start_at)
    if end_at:
        inventory_qs = inventory_qs.filter(transaction_date__lte=end_at)

    for transaction in inventory_qs[:200]:
        product_name = getattr(transaction.product, "name", "Inventory item")
        full_name = mechanic.user.get_full_name() or mechanic.user.get_username()
        available_users.add(full_name)
        activities.append({
            "id": f"inventory-{transaction.id}",
            "type": "inventory",
            "title": f"{product_name} ({transaction.transaction_type.title()})",
            "description": f"Quantity: {transaction.quantity}",
            "timestamp": _serialize_timestamp(transaction.transaction_date),
            "users": [full_name],
            "context": {
                "product_id": getattr(transaction.product, "id", None),
                "transaction_type": transaction.transaction_type,
            },
        })

    job_history_qs = (
        JobHistory.objects
        .filter(vehicle__customer__user=mechanic.user)
        .select_related("vehicle", "invoice")
        .order_by("-job_date")
    )
    if start_at:
        job_history_qs = job_history_qs.filter(job_date__gte=start_at.date())
    if end_at:
        job_history_qs = job_history_qs.filter(job_date__lte=end_at.date())

    for job in job_history_qs[:200]:
        timestamp = datetime.combine(job.job_date, time.min)
        activities.append({
            "id": f"jobhistory-{job.id}",
            "type": "workorder",
            "title": job.description[:120] if job.description else "Job history entry",
            "description": f"Vehicle {getattr(job.vehicle, 'unit_number', '') or getattr(job.vehicle, 'vin_number', '')}",
            "timestamp": _serialize_timestamp(timestamp),
            "status": "completed",
            "users": [mechanic.name] if mechanic.name else [],
            "context": {
                "vehicle_id": job.vehicle_id,
                "invoice_id": job.invoice_id,
            },
        })

    if search_term:
        activities = [
            activity for activity in activities
            if search_term in (activity.get("title", "").lower() + " " + activity.get("description", "").lower())
        ]

    if type_filter and type_filter != "all":
        activities = [activity for activity in activities if activity.get("type") == type_filter]

    if normalized_user_filters:
        activities = [
            activity for activity in activities
            if any(user.lower() in normalized_user_filters for user in activity.get("users", []))
        ]

    activities.sort(key=lambda item: item.get("timestamp") or "", reverse=True)

    total_count = len(activities)
    window = activities[offset:offset + limit]
    has_more = offset + limit < total_count

    return Response({
        "results": window,
        "meta": {
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
        },
        "available_filters": {
            "users": sorted(filter(None, available_users)),
            "types": ["workorder", "invoice", "inventory"],
        }
    })


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_job_update_details(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)
    try:
        wo = WorkOrder.objects.get(id=pk)
    except WorkOrder.DoesNotExist:
        return Response({"error": "not_found"}, status=404)
    if not WorkOrderAssignment.objects.filter(mechanic=mechanic, workorder=wo).exists():
        return Response({"error": "not_assigned"}, status=403)
    body = request.data or {}
    changed = []
    cause = body.get("cause")
    correction = body.get("correction")
    vehicleId = body.get("vehicleId")
    vehicle_vin = body.get("vehicle_vin")
    mileage = body.get("mileage")
    unit_no = body.get("unit_no")
    make_model = body.get("make_model")
    
    if cause is not None:
        wo.cause = cause
        changed.append("cause")
    if correction is not None:
        wo.correction = correction
        changed.append("correction")
    if vehicleId:
        try:
            v = Vehicle.objects.get(id=int(vehicleId))
            wo.vehicle = v
            changed.append("vehicle")
        except Exception:
            return Response({"error": "invalid_vehicle"}, status=400)
    if vehicle_vin is not None:
        wo.vehicle_vin = vehicle_vin
        changed.append("vehicle_vin")
    if mileage is not None:
        try:
            wo.mileage = float(mileage) if mileage else None
            changed.append("mileage")
        except (ValueError, TypeError):
            pass
    if unit_no is not None:
        wo.unit_no = unit_no
        changed.append("unit_no")
    if make_model is not None:
        wo.make_model = make_model
        changed.append("make_model")
    
    if changed:
        wo.save(update_fields=changed)
    return Response({"ok": True})


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_job_timer(request, pk: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)
    try:
        wo = WorkOrder.objects.get(id=pk)
    except WorkOrder.DoesNotExist:
        return Response({"error": "not_found"}, status=404)
    if not WorkOrderAssignment.objects.filter(mechanic=mechanic, workorder=wo).exists():
        return Response({"error": "not_assigned"}, status=403)
    action = (request.data or {}).get("action")
    now = dj_tz.now()
    if action == "start":
        if not wo.mechanic_started_at:
            wo.mechanic_started_at = now
        wo.mechanic_status = "in_progress"
    elif action == "pause":
        reason = (request.data or {}).get("reason") or ""
        if reason.lower().strip() in ("travel", "traveling", "travel to jobsite", "traveling to jobsite"):
            if not getattr(wo, "mechanic_travel_started_at", None):
                wo.mechanic_travel_started_at = now
            wo.mechanic_status = "travel"
        else:
            if not wo.mechanic_paused_at:
                wo.mechanic_paused_at = now
                pauses = list(getattr(wo, "mechanic_pause_log", []) or [])
                pauses.append({"start": now.isoformat(), "reason": reason})
                wo.mechanic_pause_log = pauses
            if reason:
                wo.mechanic_pause_reason = reason[:500]
            wo.mechanic_status = "paused"
    elif action == "arrived":
        if getattr(wo, "mechanic_travel_started_at", None):
            wo.mechanic_total_travel_seconds = int((now - wo.mechanic_travel_started_at).total_seconds()) + (getattr(wo, "mechanic_total_travel_seconds", 0) or 0)
            wo.mechanic_travel_started_at = None
        wo.mechanic_status = "in_progress"
    elif action == "resume":
        if wo.mechanic_paused_at:
            wo.mechanic_total_paused_seconds = int((now - wo.mechanic_paused_at).total_seconds()) + (wo.mechanic_total_paused_seconds or 0)
            pauses = list(getattr(wo, "mechanic_pause_log", []) or [])
            if pauses:
                last = pauses[-1]
                if last.get("start") and not last.get("end"):
                    last["end"] = now.isoformat()
                    try:
                        import datetime as _dt
                        st = _dt.datetime.fromisoformat(last["start"]).replace(tzinfo=None)
                        last["seconds"] = int((now.replace(tzinfo=None) - st).total_seconds())
                    except Exception:
                        pass
                    pauses[-1] = last
                    wo.mechanic_pause_log = pauses
            wo.mechanic_paused_at = None
        wo.mechanic_status = "in_progress"
    elif action == "stop":
        if not wo.mechanic_ended_at:
            wo.mechanic_ended_at = now
    elif action == "complete":
        missing = []
        if not (wo.cause and wo.cause.strip()):
            missing.append("cause")
        if not (wo.correction and wo.correction.strip()):
            missing.append("correction")
        if not getattr(wo, "signature_file", None):
            missing.append("signature")
        if missing:
            return Response({"error": "completion_requirements_missing", "missing": missing}, status=400)
        if not wo.mechanic_ended_at:
            wo.mechanic_ended_at = now
        wo.mechanic_marked_complete = True
        wo.mechanic_completed_at = now
        wo.mechanic_status = "marked_complete"
    else:
        return Response({"error": "invalid_action"}, status=400)
    wo.save(update_fields=[
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
    return Response({"ok": True, "mechanic_status": getattr(wo, "mechanic_status", "not_started")})


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_customer_vehicles_list(request, customer_id: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)
    try:
        customer = Customer.objects.get(id=customer_id, user=mechanic.user)
    except Customer.DoesNotExist:
        return Response({"error": "not_found"}, status=404)
    qs = Vehicle.objects.filter(customer=customer).order_by('unit_number', 'vin_number')
    data = [{
        "id": v.id,
        "unit_number": v.unit_number or "",
        "vin_number": v.vin_number or "",
        "make_model": v.make_model or "",
    } for v in qs]
    return Response({"vehicles": data})


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_customer_vehicle_create(request, customer_id: int):
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)
    try:
        customer = Customer.objects.get(id=customer_id, user=mechanic.user)
    except Customer.DoesNotExist:
        return Response({"error": "not_found"}, status=404)
    body = request.data or {}
    vin_number = (body.get('vin_number') or '').strip()
    unit_number = (body.get('unit_number') or '').strip() or None
    make_model = (body.get('make_model') or '').strip() or None
    if not vin_number:
        return Response({"error": "vin_required"}, status=400)
    try:
        v = Vehicle.objects.create(customer=customer, vin_number=vin_number, unit_number=unit_number, make_model=make_model)
        return Response({"id": v.id}, status=201)
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@api_view(["POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def mobile_pm_inspection_submit(request, pk: int):
    """Submit PM inspection from mobile app"""
    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)
    
    try:
        assignment = WorkOrderAssignment.objects.select_related('workorder').get(
            mechanic=mechanic, 
            workorder_id=pk
        )
    except WorkOrderAssignment.DoesNotExist:
        return Response({"error": "not_assigned"}, status=403)
    
    workorder = assignment.workorder
    payload = request.data or {}
    
    # Extract business info
    business_info = payload.get('business_info') or {}
    business_snapshot = {
        'name': str(business_info.get('name') or ''),
        'address': str(business_info.get('address') or ''),
        'phone': str(business_info.get('phone') or ''),
        'email': str(business_info.get('email') or ''),
        'website': str(business_info.get('website') or ''),
    }
    
    # Extract vehicle info
    vehicle_info = payload.get('vehicle_info') or {}
    vehicle_snapshot = {
        'unit_number': str(vehicle_info.get('unitNumber') or vehicle_info.get('unit_number') or ''),
        'vin': str(vehicle_info.get('vin') or ''),
        'make_model': str(vehicle_info.get('makeModel') or vehicle_info.get('make_model') or ''),
        'license_plate': str(vehicle_info.get('licensePlate') or vehicle_info.get('license_plate') or ''),
        'mileage': str(vehicle_info.get('mileage') or ''),
        'year': str(vehicle_info.get('year') or ''),
    }
    
    # Extract checklist
    checklist_payload = payload.get('checklist') or {}
    cleaned_checklist = {}
    allowed_statuses = {'pass', 'fail', 'na'}
    
    for item_id, entry in checklist_payload.items():
        if isinstance(entry, dict):
            status = str(entry.get('status') or '').lower()
            if status in allowed_statuses:
                cleaned_checklist[item_id] = {
                    'status': status,
                    'notes': str(entry.get('notes') or ''),
                }
    
    # Extract measurements
    measurements = payload.get('measurements') or {}
    cleaned_measurements = {
        'pushrod_stroke': {},
        'tread_depth': {},
    }
    
    if isinstance(measurements.get('pushrodStroke'), dict):
        for k, v in measurements['pushrodStroke'].items():
            cleaned_measurements['pushrod_stroke'][k] = str(v or '')
    
    if isinstance(measurements.get('treadDepth'), dict):
        for k, v in measurements['treadDepth'].items():
            cleaned_measurements['tread_depth'][k] = str(v or '')
    
    cleaned_checklist['_measurements'] = cleaned_measurements
    
    # Create or update PM inspection
    inspection, created = PMInspection.objects.get_or_create(
        workorder=workorder,
        defaults={'assignment': assignment}
    )
    
    if not inspection.assignment:
        inspection.assignment = assignment
    
    inspection.business_snapshot = business_snapshot
    inspection.vehicle_snapshot = vehicle_snapshot
    inspection.checklist = cleaned_checklist
    inspection.additional_notes = str(payload.get('additional_notes') or '')
    inspection.inspector_name = str(payload.get('inspector_name') or '')
    inspection.inspection_date = str(payload.get('inspection_date') or '')
    inspection.customer_name = str(payload.get('customer_name') or workorder.customer.name if workorder.customer else '')
    inspection.location = str(payload.get('location') or '')
    overall_status = str(payload.get('overall_status') or '').lower()
    if overall_status not in {'pass', 'fail'}:
        overall_status = ''
    inspection.overall_status = overall_status
    inspection.submitted_at = timezone.now()
    inspection.save()
    
    return Response({
        'status': 'success',
        'message': 'PM inspection submitted successfully.',
        'inspection_id': inspection.id,
    })


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mobile_pm_inspection_detail(request, pk: int):
    """Return an existing PM inspection so mechanics can continue editing."""

    mechanic = _require_mechanic(request)
    if not mechanic:
        return Response({"error": "not_a_mechanic"}, status=403)

    try:
        assignment = WorkOrderAssignment.objects.select_related('workorder').get(
            mechanic=mechanic,
            workorder_id=pk
        )
    except WorkOrderAssignment.DoesNotExist:
        return Response({"error": "not_assigned"}, status=403)

    workorder = assignment.workorder

    try:
        inspection = workorder.pm_inspection
    except PMInspection.DoesNotExist:
        return Response({"error": "not_found"}, status=404)

    checklist_data = inspection.checklist or {}
    allowed_statuses = {'pass', 'fail', 'na'}
    status_map: dict[str, str] = {}
    notes_map: dict[str, str] = {}

    if isinstance(checklist_data, dict):
        for item_id, entry in checklist_data.items():
            if not isinstance(item_id, str) or item_id.startswith('_'):
                continue

            if isinstance(entry, dict):
                status = str(entry.get('status') or '').lower()
                if status in allowed_statuses:
                    status_map[item_id] = status

                notes = entry.get('notes')
                if isinstance(notes, str):
                    notes_map[item_id] = notes

    measurements_payload = checklist_data.get('_measurements') if isinstance(checklist_data, dict) else {}

    def _coerce_measurements(source):
        result = {}
        if isinstance(source, dict):
            for key, value in source.items():
                if isinstance(value, (str, int, float)):
                    result[str(key)] = str(value)
        return result

    pushrod_values = {}
    tread_depth_values = {}

    if isinstance(measurements_payload, dict):
        pushrod_values = _coerce_measurements(measurements_payload.get('pushrod_stroke'))
        tread_depth_values = _coerce_measurements(measurements_payload.get('tread_depth'))

    response_payload = {
        'inspector_name': inspection.inspector_name,
        'inspection_date': inspection.inspection_date,
        'additional_notes': inspection.additional_notes,
        'business_info': inspection.business_snapshot or {},
        'vehicle_info': inspection.vehicle_snapshot or {},
        'status_map': status_map,
        'notes_map': notes_map,
        'measurements': {
            'pushrodStroke': pushrod_values,
            'treadDepth': tread_depth_values,
        },
        'customer_name': inspection.customer_name,
        'location': inspection.location,
        'overall_status': inspection.overall_status,
        'submitted_at': inspection.submitted_at.isoformat() if inspection.submitted_at else None,
    }

    return Response(response_payload)

