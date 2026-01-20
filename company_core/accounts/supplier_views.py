"""Views powering the supplier portal experience."""

from django.db.models import Case, Count, F, FloatField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .decorators import supplier_login_required
from .models import InventoryTransaction, MechExpense
from .utils import resolve_company_logo_url


def _business_contact_details(supplier):
    profile = getattr(supplier.user, "profile", None)
    company_name = None
    company_email = None
    company_phone = None
    company_address = None
    company_logo_url = None

    if profile:
        company_name = getattr(profile, "company_name", None)
        company_email = getattr(profile, "company_email", None)
        company_phone = getattr(profile, "company_phone", None)
        company_address = getattr(profile, "company_address", None)
        company_logo_url = resolve_company_logo_url(profile)

    return {
        "name": company_name
        or supplier.user.get_full_name()
        or supplier.user.username,
        "email": company_email or supplier.user.email,
        "phone": company_phone,
        "address": company_address,
        "logo_url": company_logo_url,
        "support_url": f"{reverse('accounts:contact_support')}?source=supplier_portal",
    }


def _normalized_supplier_name(supplier):
    """Return a consistently formatted supplier name for lookups."""

    return (supplier.name or "").strip()


def _supplier_receipts_queryset(supplier):
    """Base queryset for receipts associated with the supplier."""

    supplier_name = _normalized_supplier_name(supplier)
    filters = Q(user=supplier.user)
    if supplier_name:
        filters &= Q(vendor__iexact=supplier_name)
    else:
        filters &= Q(vendor__exact="")

    return MechExpense.objects.filter(filters)


def build_supplier_portal_context(request):
    supplier_account = request.user.supplier_portal
    return {
        "supplier_account": supplier_account,
        "business_contact": _business_contact_details(supplier_account),
        "active_supplier_page": getattr(getattr(request, "resolver_match", None), "url_name", None),
    }


@supplier_login_required
def supplier_dashboard(request):
    supplier_account = request.user.supplier_portal

    product_queryset = supplier_account.products.all()

    product_summary = product_queryset.aggregate(
        total_products=Coalesce(Count("id"), Value(0)),
        total_stock=Coalesce(Sum("quantity_in_stock"), Value(0)),
    )

    total_purchased = (
        InventoryTransaction.objects.filter(
            product__supplier=supplier_account,
            transaction_type="IN",
        ).aggregate(total=Coalesce(Sum("quantity"), Value(0)))
    )["total"]
    total_purchased = int(total_purchased or 0)

    low_stock_count = product_queryset.filter(
        quantity_in_stock__lt=F("reorder_level"),
        reorder_level__gt=0,
    ).count()

    product_rows = product_queryset.annotate(
        total_received=Coalesce(
            Sum(
                "transactions__quantity",
                filter=Q(transactions__transaction_type="IN"),
            ),
            Value(0),
        ),
        total_used=Coalesce(
            Sum(
                "transactions__quantity",
                filter=Q(transactions__transaction_type="OUT"),
            ),
            Value(0),
        ),
    ).order_by("name")

    recent_transactions = (
        InventoryTransaction.objects.filter(product__supplier=supplier_account)
        .select_related("product")
        .order_by("-transaction_date")[:6]
    )

    context = {
        **build_supplier_portal_context(request),
        "summary": {
            "total_products": int(product_summary.get("total_products", 0) or 0),
            "total_stock": int(product_summary.get("total_stock", 0) or 0),
            "total_purchased": total_purchased,
            "low_stock": low_stock_count,
        },
        "products": product_rows,
        "recent_transactions": recent_transactions,
    }
    return render(request, "suppliers/dashboard.html", context)


@supplier_login_required
def supplier_receipts(request):
    supplier_account = request.user.supplier_portal

    base_queryset = _supplier_receipts_queryset(supplier_account).annotate(
        items_subtotal=Coalesce(Sum("mechexpenseitem__amount"), Value(0.0)),
        items_tax=Coalesce(Sum("mechexpenseitem__tax_paid"), Value(0.0)),
    )

    total_amount_expression = Case(
        When(tax_included=True, then=F("items_subtotal")),
        default=F("items_subtotal") + F("items_tax"),
        output_field=FloatField(),
    )

    receipts = base_queryset.annotate(
        total_amount=total_amount_expression,
        pending_amount=Case(
            When(paid=False, then=total_amount_expression),
            default=Value(0.0),
            output_field=FloatField(),
        ),
    ).order_by("-date", "-id")

    aggregates = receipts.aggregate(
        total_receipts=Count("id", distinct=True),
        paid_receipts=Count("id", filter=Q(paid=True), distinct=True),
        unpaid_receipts=Count("id", filter=Q(paid=False), distinct=True),
        total_volume=Coalesce(Sum("total_amount"), Value(0.0)),
        pending_balance=Coalesce(Sum("pending_amount"), Value(0.0)),
    )

    summary = {
        "total_receipts": int(aggregates.get("total_receipts", 0) or 0),
        "paid_receipts": int(aggregates.get("paid_receipts", 0) or 0),
        "unpaid_receipts": int(aggregates.get("unpaid_receipts", 0) or 0),
        "total_volume": float(aggregates.get("total_volume", 0.0) or 0.0),
        "pending_balance": float(aggregates.get("pending_balance", 0.0) or 0.0),
    }

    context = {
        **build_supplier_portal_context(request),
        "receipts": receipts,
        "summary": summary,
    }

    return render(request, "suppliers/receipt_list.html", context)


@supplier_login_required
def supplier_receipt_detail(request, receipt_id):
    supplier_account = request.user.supplier_portal
    receipt = get_object_or_404(
        _supplier_receipts_queryset(supplier_account).prefetch_related("mechexpenseitem_set"),
        pk=receipt_id,
    )

    line_items = list(receipt.mechexpenseitem_set.all())
    subtotal = sum(item.amount for item in line_items)
    tax_total = sum(item.tax_paid for item in line_items)
    total_amount = subtotal if receipt.tax_included else subtotal + tax_total
    pending_balance = total_amount if not receipt.paid else 0

    context = {
        **build_supplier_portal_context(request),
        "receipt": receipt,
        "line_items": line_items,
        "totals": {
            "subtotal": subtotal,
            "tax_total": tax_total,
            "total_amount": total_amount,
            "pending_balance": pending_balance,
        },
    }

    return render(request, "suppliers/receipt_detail.html", context)
