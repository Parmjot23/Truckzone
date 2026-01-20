from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.template.loader import render_to_string
from django.db import transaction
from django.db.models import Q, F, Sum, ExpressionWrapper, DecimalField, Max
from django.db.models.functions import Coalesce, TruncDate
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.urls import reverse  # for building URL for redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import timedelta, datetime, date
import json
import qrcode
import os
import textwrap
import re
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .models import (
    Category,
    CategoryGroup,
    CategoryAttribute,
    CategoryAttributeOption,
    Supplier,
    Product,
    InventoryTransaction,
    InventoryLocation,
    Profile,
    ProductBrand,
    ProductModel,
    ProductVin,
)
from .utils import get_product_user_ids, get_product_stock_user_ids
from .forms import (
    CategoryForm,
    CategoryGroupForm,
    CategoryAttributeForm,
    SupplierForm,
    ProductForm,
    ProductAttributeForm,
    ProductInlineForm,
    ProductBrandForm,
    ProductModelForm,
    ProductVinForm,
    InventoryTransactionForm,
    InventoryLocationForm,
)
from .excel_formatting import apply_template_styling


PRODUCT_TEMPLATE_HEADERS = [
    "SKU",
    "Name",
    "Description",
    "Category",
    "Supplier",
    "Brand",
    "Model",
    "VIN",
    "Item Type",
    "Cost Price",
    "Sale Price",
    "Promotion Price",
    "Margin",
    "Quantity",
    "Reorder Level",
    "Location",
    "Warranty Expiry Date",
    "Warranty Length (Days)",
    "Show on Storefront",
    "Featured",
]


SUPPLIER_TEMPLATE_HEADERS = [
    "Name",
    "Contact Person",
    "Email",
    "Phone Number",
    "Address",
]


CATEGORY_TEMPLATE_HEADERS = [
    "Name",
    "Description",
    "Group",
    "Parent Category",
    "Sort Order",
    "Active",
]


CATEGORY_GROUP_TEMPLATE_HEADERS = [
    "Name",
    "Description",
    "Sort Order",
    "Active",
]


BRAND_TEMPLATE_HEADERS = [
    "Name",
    "Description",
    "Sort Order",
    "Active",
]


MODEL_TEMPLATE_HEADERS = [
    "Name",
    "Brand",
    "Description",
    "Year Start",
    "Year End",
    "Sort Order",
    "Active",
]


VIN_TEMPLATE_HEADERS = [
    "VIN",
    "Description",
    "Sort Order",
    "Active",
]


LOCATION_TEMPLATE_HEADERS = [
    "Name",
]


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _form_errors_json(form):
    return {field: [str(err) for err in errs] for field, errs in form.errors.items()}


def _paginate_queryset(request, queryset, per_page=100):
    """Return a single page of objects and the current querystring sans page."""

    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    params = request.GET.copy()
    params.pop("page", None)
    return page_obj, params.urlencode()


def _get_inventory_user_ids(request):
    if not hasattr(request, "_inventory_user_ids"):
        request._inventory_user_ids = get_product_user_ids(request.user)
    return request._inventory_user_ids


def _get_inventory_stock_user_ids(request):
    if not hasattr(request, "_inventory_stock_user_ids"):
        request._inventory_stock_user_ids = get_product_stock_user_ids(request.user)
    return request._inventory_stock_user_ids


@login_required
def inventory_view(request):
    tab = request.GET.get("tab")
    if tab == "transactions":
        return redirect("accounts:inventory_transactions")
    if tab == "products":
        return redirect("accounts:inventory_products")
    if tab == "suppliers":
        return redirect("accounts:inventory_suppliers")
    if tab == "categories":
        return redirect("accounts:inventory_categories")
    if tab == "locations":
        return redirect("accounts:inventory_locations")
    return redirect("accounts:inventory_hub")

@login_required
def inventory_hub(request):
    user = request.user
    stock_user_ids = _get_inventory_stock_user_ids(request)
    now = timezone.now()
    window_days = 30
    window_start_date = now.date() - timedelta(days=window_days - 1)
    recent_period_start = now - timedelta(days=window_days)

    products = Product.objects.filter(user__in=stock_user_ids).select_related("category", "supplier")
    transactions = (
        InventoryTransaction.objects.filter(product__user__in=stock_user_ids)
        .select_related("product", "product__category")
    )

    price_expr = Coalesce("sale_price", "cost_price")
    value_expr = ExpressionWrapper(
        F("quantity_in_stock") * price_expr,
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    totals = products.aggregate(
        total_value=Sum(value_expr),
        total_qty=Sum("quantity_in_stock"),
    )
    total_inventory_value = totals.get("total_value") or Decimal("0.00")
    total_quantity = totals.get("total_qty") or 0

    low_stock_qs = products.filter(quantity_in_stock__lt=F("reorder_level"))
    low_stock_count = low_stock_qs.count()
    out_of_stock_count = products.filter(quantity_in_stock__lte=0).count()

    top_selling = (
        products.annotate(
            qty_sold=Sum(
                "transactions__quantity",
                filter=Q(
                    transactions__transaction_type="OUT",
                    transactions__transaction_date__gte=recent_period_start,
                ),
            )
        )
        .filter(qty_sold__gt=0)
        .order_by("-qty_sold", "name")
        .first()
    )

    category_rows = (
        products.values("category__name")
        .annotate(
            value=Sum(value_expr),
            qty=Sum("quantity_in_stock"),
        )
        .order_by("-value")
    )
    category_breakdown = []
    for row in category_rows:
        category_breakdown.append(
            {
                "name": row["category__name"] or "Uncategorized",
                "value": row["value"] or Decimal("0.00"),
                "qty": row["qty"] or 0,
            }
        )

    movement_rows = (
        transactions.filter(transaction_date__date__gte=window_start_date)
        .annotate(day=TruncDate("transaction_date"))
        .values("day")
        .annotate(
            stock_in=Sum("quantity", filter=Q(transaction_type="IN")),
            stock_out=Sum("quantity", filter=Q(transaction_type="OUT")),
        )
    )
    movement_lookup = {
        row["day"]: {
            "stock_in": row["stock_in"] or 0,
            "stock_out": row["stock_out"] or 0,
        }
        for row in movement_rows
    }

    movement_labels = []
    stock_in_series = []
    stock_out_series = []
    for offset in range(window_days):
        day = window_start_date + timedelta(days=offset)
        movement_labels.append(str(day.day))
        day_data = movement_lookup.get(day, {"stock_in": 0, "stock_out": 0})
        stock_in_series.append(day_data.get("stock_in") or 0)
        stock_out_series.append(day_data.get("stock_out") or 0)

    stock_in_total = sum(stock_in_series)
    stock_out_total = sum(stock_out_series)
    net_change = stock_in_total - stock_out_total
    value_trend_percent = round((net_change / total_quantity) * 100, 2) if total_quantity else 0
    trend_direction = "up" if value_trend_percent >= 0 else "down"

    product_form = ProductForm(user=user)
    supplier_form = SupplierForm(user=user)
    category_form = CategoryForm(user=user)
    location_form = InventoryLocationForm(user=user)

    recent_transactions_qs = transactions.order_by("-transaction_date")[:6]
    recent_transactions = []
    for tx in recent_transactions_qs:
        unit_price = (
            tx.product.sale_price
            if tx.product.sale_price is not None
            else tx.product.cost_price
            or Decimal("0.00")
        )
        total_value = (unit_price or Decimal("0.00")) * Decimal(tx.quantity)
        recent_transactions.append(
            {
                "id": tx.id,
                "product": tx.product.name,
                "type": tx.get_transaction_type_display(),
                "type_code": tx.transaction_type,
                "quantity": tx.quantity,
                "date": tx.transaction_date,
                "value": total_value,
                "remarks": tx.remarks or "",
            }
        )

    category_total_value = sum((c["value"] for c in category_breakdown), Decimal("0.00"))
    if category_total_value:
        for entry in category_breakdown:
            entry["percent"] = float((entry["value"] / category_total_value) * Decimal("100"))
    else:
        for entry in category_breakdown:
            entry["percent"] = 0
    category_chart_labels = [c["name"] for c in category_breakdown]
    category_chart_values = [float(c["value"]) for c in category_breakdown]

    movement_chart = {
        "labels": movement_labels,
        "stock_in": stock_in_series,
        "stock_out": stock_out_series,
    }

    context = {
        "total_inventory_value": total_inventory_value,
        "total_quantity": total_quantity,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "top_selling": top_selling,
        "category_breakdown": category_breakdown,
        "category_total_value": category_total_value,
        "category_chart_labels": category_chart_labels,
        "category_chart_values": category_chart_values,
        "movement_chart": movement_chart,
        "stock_in_total": stock_in_total,
        "stock_out_total": stock_out_total,
        "value_trend_percent": value_trend_percent,
        "trend_direction": trend_direction,
        "recent_transactions": recent_transactions,
        "window_days": window_days,
        "product_form": product_form,
        "supplier_form": supplier_form,
        "category_form": category_form,
        "location_form": location_form,
    }
    return render(request, "inventory/hub.html", context)

@login_required
def inventory_transactions_view(request):
    query = request.GET.get("q", "").strip()
    stock_user_ids = _get_inventory_stock_user_ids(request)
    transactions = (
        InventoryTransaction.objects.filter(product__user__in=stock_user_ids)
        .select_related("product", "product__supplier", "product__category")
        .order_by("-transaction_date")
    )

    if query:
        transactions = transactions.filter(
            Q(product__name__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(remarks__icontains=query)
            | Q(product__category__name__icontains=query)
            | Q(product__supplier__name__icontains=query)
        )

    transactions_page, querystring = _paginate_queryset(request, transactions, per_page=100)

    context = {
        "transactions_page": transactions_page,
        "query": query,
        "querystring": querystring,
    }
    return render(request, "inventory/transactions_list.html", context)

@login_required
def inventory_products_view(request):
    search_query = request.GET.get("q", "").strip()
    group_ids = _extract_ids(request.GET.getlist("group"))
    category_ids = _extract_ids(request.GET.getlist("category"))
    brand_ids = _extract_ids(request.GET.getlist("brand"))
    product_user_ids = _get_inventory_user_ids(request)
    stock_user_ids = _get_inventory_stock_user_ids(request)
    products_qs = (
        Product.objects.filter(user__in=product_user_ids)
        .select_related("supplier", "category", "brand", "vehicle_model", "vin_number")
        .order_by("name")
    )

    if search_query:
        products_qs = products_qs.filter(
            Q(name__icontains=search_query)
            | Q(sku__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(category__name__icontains=search_query)
            | Q(supplier__name__icontains=search_query)
            | Q(brand__name__icontains=search_query)
            | Q(vehicle_model__name__icontains=search_query)
            | Q(vin_number__vin__icontains=search_query)
            | Q(location__icontains=search_query)
        )

    if group_ids:
        products_qs = products_qs.filter(category__group_id__in=group_ids)
    if category_ids:
        products_qs = products_qs.filter(category_id__in=category_ids)
    if brand_ids:
        products_qs = products_qs.filter(brand_id__in=brand_ids)

    products_page, querystring = _paginate_queryset(request, products_qs, per_page=100)
    categories = Category.objects.filter(user__in=product_user_ids).order_by("name")
    category_groups = CategoryGroup.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    suppliers = Supplier.objects.filter(user__in=product_user_ids).order_by("name")
    brands = ProductBrand.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    models = ProductModel.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    vins = ProductVin.objects.filter(user__in=product_user_ids).order_by("sort_order", "vin")
    locations = InventoryLocation.objects.filter(user__in=product_user_ids).order_by("name")
    item_type_choices = Product._meta.get_field("item_type").choices
    return render(
        request,
        "inventory/products_list.html",
        {
            "products": products_page,
            "products_count": products_page.paginator.count,
            "categories": categories,
            "category_groups": category_groups,
            "suppliers": suppliers,
            "brands": brands,
            "models": models,
            "vins": vins,
            "locations": locations,
            "item_type_choices": item_type_choices,
            "search_query": search_query,
            "selected_group_ids": [str(value) for value in group_ids],
            "selected_category_ids": [str(value) for value in category_ids],
            "selected_brand_ids": [str(value) for value in brand_ids],
            "stock_user_ids": stock_user_ids,
            "querystring": querystring,
        },
    )

@login_required
def inventory_suppliers_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    suppliers_qs = Supplier.objects.filter(user__in=product_user_ids).order_by("name")

    if search_query:
        suppliers_qs = suppliers_qs.filter(
            Q(name__icontains=search_query)
            | Q(contact_person__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone_number__icontains=search_query)
            | Q(address__icontains=search_query)
        )

    suppliers = list(suppliers_qs)
    return render(
        request,
        "inventory/suppliers_list.html",
        {
            "suppliers": suppliers,
            "suppliers_count": len(suppliers),
            "search_query": search_query,
        },
    )

@login_required
def inventory_categories_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    categories_qs = (
        Category.objects.filter(user__in=product_user_ids)
        .select_related("group", "parent")
        .order_by("sort_order", "name")
    )

    if search_query:
        categories_qs = categories_qs.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )

    categories = list(categories_qs)
    category_groups = CategoryGroup.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    return render(
        request,
        "inventory/categories_list.html",
        {
            "categories": categories,
            "categories_count": len(categories),
            "search_query": search_query,
            "category_groups": category_groups,
        },
    )


@login_required
def inventory_category_groups_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    groups_qs = CategoryGroup.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    if search_query:
        groups_qs = groups_qs.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )
    groups = list(groups_qs)
    return render(
        request,
        "inventory/category_groups_list.html",
        {
            "groups": groups,
            "groups_count": len(groups),
            "search_query": search_query,
        },
    )


@login_required
def inventory_attributes_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    attributes_qs = (
        CategoryAttribute.objects.filter(user__in=product_user_ids)
        .select_related("category")
        .order_by("sort_order", "name")
    )
    if search_query:
        attributes_qs = attributes_qs.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(category__name__icontains=search_query)
            | Q(value_unit__icontains=search_query)
        )
    attributes = list(attributes_qs)
    for attribute in attributes:
        attribute.active_options = [
            option.value for option in attribute.options.all() if option.is_active
        ]
    categories = Category.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    attribute_types = CategoryAttribute._meta.get_field("attribute_type").choices
    return render(
        request,
        "inventory/attributes_list.html",
        {
            "attributes": attributes,
            "attributes_count": len(attributes),
            "categories": categories,
            "attribute_types": attribute_types,
            "search_query": search_query,
        },
    )


@login_required
def inventory_brands_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    brands_qs = ProductBrand.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    if search_query:
        brands_qs = brands_qs.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )
    brands = list(brands_qs)
    return render(
        request,
        "inventory/brands_list.html",
        {
            "brands": brands,
            "brands_count": len(brands),
            "search_query": search_query,
        },
    )


@login_required
def inventory_models_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    models_qs = (
        ProductModel.objects.filter(user__in=product_user_ids)
        .select_related("brand")
        .order_by("sort_order", "name")
    )
    if search_query:
        models_qs = models_qs.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(brand__name__icontains=search_query)
        )
    models = list(models_qs)
    brands = ProductBrand.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    return render(
        request,
        "inventory/models_list.html",
        {
            "models": models,
            "models_count": len(models),
            "brands": brands,
            "search_query": search_query,
        },
    )


@login_required
def inventory_vins_view(request):
    search_query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    vins_qs = ProductVin.objects.filter(user__in=product_user_ids).order_by("sort_order", "vin")
    if search_query:
        vins_qs = vins_qs.filter(
            Q(vin__icontains=search_query) | Q(description__icontains=search_query)
        )
    vins = list(vins_qs)
    return render(
        request,
        "inventory/vins_list.html",
        {
            "vins": vins,
            "vins_count": len(vins),
            "search_query": search_query,
        },
    )

@login_required
def inventory_locations_view(request):
    query = request.GET.get("q", "").strip()
    product_user_ids = _get_inventory_user_ids(request)
    locations = InventoryLocation.objects.filter(user__in=product_user_ids).order_by("name")

    if query:
        locations = locations.filter(name__icontains=query)

    locations_page, querystring = _paginate_queryset(request, locations, per_page=100)
    location_form = InventoryLocationForm(user=request.user)
    return render(
        request,
        "inventory/locations_list.html",
        {
            "locations_page": locations_page,
            "location_form": location_form,
            "query": query,
            "querystring": querystring,
        },
    )


##############################
# AJAX "get form" endpoints  #
##############################
@login_required
def get_transaction_form(request):
    transaction_id = request.GET.get("transaction_id")
    if not transaction_id:
        return HttpResponseBadRequest("Transaction ID not provided.")
    stock_user_ids = _get_inventory_stock_user_ids(request)
    transaction = get_object_or_404(
        InventoryTransaction, id=transaction_id, product__user__in=stock_user_ids
    )
    form = InventoryTransactionForm(user=request.user, instance=transaction)
    html = render_to_string(
        "inventory/partials/_transaction_form.html", {"form": form}, request=request
    )
    return JsonResponse({"html": html})


@login_required
def get_supplier_form(request):
    supplier_id = request.GET.get("supplier_id")
    if not supplier_id:
        return HttpResponseBadRequest("Supplier ID not provided.")
    product_user_ids = _get_inventory_user_ids(request)
    supplier = get_object_or_404(Supplier, id=supplier_id, user__in=product_user_ids)
    form = SupplierForm(user=request.user, instance=supplier)
    html = render_to_string(
        "inventory/partials/_supplier_form.html", {"form": form}, request=request
    )
    return JsonResponse({"html": html})


@login_required
def get_product_form(request):
    product_id = request.GET.get("product_id")
    if not product_id:
        return HttpResponseBadRequest("Product ID not provided.")
    product_user_ids = _get_inventory_user_ids(request)
    product = get_object_or_404(Product, id=product_id, user__in=product_user_ids)
    stock_user_ids = _get_inventory_stock_user_ids(request)
    stock_visible = product.user_id in stock_user_ids
    attributes_only = request.GET.get("attributes_only")
    if attributes_only:
        form = ProductAttributeForm(user=request.user, instance=product)
        template_name = "inventory/partials/_product_attribute_form.html"
    else:
        form = ProductForm(user=request.user, instance=product)
        template_name = "inventory/partials/_product_form.html"
    html = render_to_string(
        template_name, {"form": form, "stock_visible": stock_visible}, request=request
    )
    return JsonResponse({"html": html})


@login_required
def get_attribute_fields(request):
    category_id = request.GET.get("category_id")
    product_id = request.GET.get("product_id")
    product = None
    if product_id:
        product_user_ids = _get_inventory_user_ids(request)
        product = get_object_or_404(Product, id=product_id, user__in=product_user_ids)
    form = ProductForm(user=request.user, instance=product, category_id=category_id)
    html = render_to_string(
        "inventory/partials/_attribute_fields.html", {"form": form}, request=request
    )
    return JsonResponse({"html": html})


@login_required
def get_category_form(request):
    category_id = request.GET.get("category_id")
    if not category_id:
        return HttpResponseBadRequest("Category ID not provided.")
    product_user_ids = _get_inventory_user_ids(request)
    category = get_object_or_404(Category, id=category_id, user__in=product_user_ids)
    form = CategoryForm(user=request.user, instance=category)
    html = render_to_string(
        "inventory/partials/_category_form.html", {"form": form}, request=request
    )
    return JsonResponse({"html": html})


@login_required
def get_location_form(request):
    location_id = request.GET.get("location_id")
    if not location_id:
        return HttpResponseBadRequest("Location ID not provided.")
    product_user_ids = _get_inventory_user_ids(request)
    location = get_object_or_404(InventoryLocation, id=location_id, user__in=product_user_ids)
    form = InventoryLocationForm(user=request.user, instance=location)
    html = render_to_string(
        "inventory/partials/_location_form.html", {"form": form}, request=request
    )
    return JsonResponse({"html": html})


##############################
# Transaction CRUD           #
##############################
@login_required
def add_transaction(request):
    if request.method == "POST":
        form = InventoryTransactionForm(user=request.user, data=request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            stock_user_ids = _get_inventory_stock_user_ids(request)
            if transaction.product.user_id not in stock_user_ids:
                messages.error(
                    request, "Not authorized to add a transaction for this product."
                )
            else:
                try:
                    transaction.save()
                    messages.success(request, "Transaction added successfully.")
                except ValidationError as e:
                    messages.error(request, e.message)
        else:
            messages.error(
                request, "Error adding transaction. Please check form for errors."
            )
    # Redirect back to Transactions tab
    return redirect(reverse("accounts:inventory_transactions"))


@login_required
def edit_transaction(request):
    if request.method == "POST":
        transaction_id = request.POST.get("transaction_id")
        stock_user_ids = _get_inventory_stock_user_ids(request)
        transaction = get_object_or_404(
            InventoryTransaction, id=transaction_id, product__user__in=stock_user_ids
        )
        form = InventoryTransactionForm(
            user=request.user, data=request.POST, instance=transaction
        )
        if form.is_valid():
            try:
                form.save()
                messages.success(request, "Transaction updated successfully.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            messages.error(
                request, "Error updating transaction. Please check form for errors."
            )
    # Return to Transactions tab
    return redirect(reverse("accounts:inventory_transactions"))


@login_required
def delete_transaction(request):
    if request.method == "POST":
        transaction_id = request.POST.get("transaction_id")
        stock_user_ids = _get_inventory_stock_user_ids(request)
        transaction = get_object_or_404(
            InventoryTransaction, id=transaction_id, product__user__in=stock_user_ids
        )
        transaction.delete()
        messages.success(request, "Transaction deleted successfully.")
    else:
        messages.error(request, "Invalid request method.")
    # Return to Transactions tab
    return redirect(reverse("accounts:inventory_transactions"))


##############################
# Supplier CRUD              #
##############################
@login_required
def add_supplier(request):
    next_url = request.POST.get("next") or request.GET.get("next") or (reverse("accounts:inventory_suppliers"))
    if request.method == "POST":
        form = SupplierForm(request.POST, user=request.user)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.user = request.user
            supplier.save()
            messages.success(request, "Supplier added successfully.")
            if _is_ajax(request):
                return JsonResponse(
                    {"success": True, "value": supplier.id, "label": supplier.name}
                )
        else:
            messages.error(
                request, "Error adding supplier. Please check the form for errors."
            )
            if _is_ajax(request):
                return JsonResponse(
                    {"success": False, "errors": _form_errors_json(form)}, status=400
                )
    # Return to Suppliers tab
    return redirect(next_url)


@login_required
def edit_supplier(request):
    if request.method == "POST":
        supplier_id = request.POST.get("supplier_id")
        product_user_ids = _get_inventory_user_ids(request)
        supplier = get_object_or_404(Supplier, id=supplier_id, user__in=product_user_ids)
        form = SupplierForm(request.POST, user=request.user, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier updated successfully.")
        else:
            messages.error(
                request, "Error updating supplier. Please check the form for errors."
            )
    # Return to Suppliers tab
    return redirect(reverse("accounts:inventory_suppliers"))


@login_required
def delete_supplier(request):
    if request.method == "POST":
        supplier_id = request.POST.get("supplier_id")
        product_user_ids = _get_inventory_user_ids(request)
        supplier = get_object_or_404(Supplier, id=supplier_id, user__in=product_user_ids)
        supplier.delete()
        messages.success(request, "Supplier deleted successfully.")
    else:
        messages.error(request, "Invalid request method.")
    # Return to Suppliers tab
    return redirect(reverse("accounts:inventory_suppliers"))


@login_required
@require_POST
def bulk_delete_suppliers(request):
    supplier_ids = _extract_ids(request.POST.getlist("supplier_ids"))
    if not supplier_ids:
        messages.warning(request, "No suppliers were selected for deletion.")
        return redirect(reverse("accounts:inventory_suppliers"))

    product_user_ids = _get_inventory_user_ids(request)
    queryset = Supplier.objects.filter(user__in=product_user_ids, id__in=supplier_ids)
    deleted_count = queryset.count()

    if not deleted_count:
        messages.warning(request, "No matching suppliers were found to delete.")
    else:
        queryset.delete()
        messages.success(request, f"Deleted {deleted_count} supplier(s).")

    return redirect(reverse("accounts:inventory_suppliers"))


@login_required
@require_POST
def save_supplier_inline(request):
    """Create or update a supplier via inline editing."""

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid data submitted."}, status=400)

    supplier_id_raw = payload.get("id")
    supplier_instance = None
    if supplier_id_raw:
        try:
            supplier_pk = int(supplier_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid supplier identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        supplier_instance = get_object_or_404(Supplier, pk=supplier_pk, user__in=product_user_ids)

    form_data = {
        "name": payload.get("name", ""),
        "contact_person": payload.get("contact_person", ""),
        "email": payload.get("email", ""),
        "phone_number": payload.get("phone_number", ""),
        "address": payload.get("address", ""),
    }
    form = SupplierForm(form_data, instance=supplier_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    supplier = form.save(commit=False)
    if not supplier.user_id:
        supplier.user = request.user
    supplier.save()

    response_data = {
        "supplier": {
            "id": supplier.pk,
            "name": supplier.name,
            "contact_person": supplier.contact_person or "",
            "email": supplier.email or "",
            "phone_number": supplier.phone_number or "",
            "address": supplier.address or "",
        }
    }
    status_code = 200 if supplier_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_inventory_supplier(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    supplier = get_object_or_404(Supplier, pk=pk, user__in=product_user_ids)
    supplier.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_suppliers")
    messages.success(request, "Supplier deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def save_category_inline(request):
    """Create or update a category via inline editing."""

    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)

    category_id_raw = payload.get("id")
    category_instance = None
    if category_id_raw:
        try:
            category_pk = int(category_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid category identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        category_instance = get_object_or_404(Category, pk=category_pk, user__in=product_user_ids)

    def _normalize(value, default=""):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip()

    def _normalize_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    form_data = {
        "name": _normalize(payload.get("name", "")),
        "description": _normalize(payload.get("description", "")),
        "group": _normalize(payload.get("group_id", payload.get("group")), None),
        "parent": _normalize(payload.get("parent_id", payload.get("parent")), None),
        "sort_order": _normalize(payload.get("sort_order", 0), 0),
        "is_active": _normalize_bool(payload.get("is_active"), True),
    }
    form = CategoryForm(form_data, files=request.FILES, instance=category_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    category = form.save(commit=False)
    if not category.user_id:
        category.user = request.user
    category.save()

    response_data = {
        "category": {
            "id": category.pk,
            "name": category.name,
            "description": category.description or "",
            "group": {
                "id": category.group_id,
                "name": category.group.name if category.group else "",
            },
            "parent": {
                "id": category.parent_id,
                "name": category.parent.name if category.parent else "",
            },
            "sort_order": category.sort_order,
            "is_active": category.is_active,
            "image_url": category.image.url if category.image else "",
        }
    }
    status_code = 200 if category_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_inventory_category(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    category = get_object_or_404(Category, pk=pk, user__in=product_user_ids)
    category.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_categories")
    messages.success(request, "Category deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def save_category_group_inline(request):
    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)

    group_id_raw = payload.get("id")
    group_instance = None
    if group_id_raw:
        try:
            group_pk = int(group_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid group identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        group_instance = get_object_or_404(CategoryGroup, pk=group_pk, user__in=product_user_ids)

    def _normalize(value, default=""):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip()

    def _normalize_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    form_data = {
        "name": _normalize(payload.get("name", "")),
        "description": _normalize(payload.get("description", "")),
        "sort_order": _normalize(payload.get("sort_order", 0), 0),
        "is_active": _normalize_bool(payload.get("is_active"), True),
    }
    form = CategoryGroupForm(form_data, files=request.FILES, instance=group_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    group = form.save(commit=False)
    if not group.user_id:
        group.user = request.user
    group.save()

    response_data = {
        "group": {
            "id": group.pk,
            "name": group.name,
            "description": group.description or "",
            "sort_order": group.sort_order,
            "is_active": group.is_active,
            "image_url": group.image.url if group.image else "",
        }
    }
    status_code = 200 if group_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_category_group(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    group = get_object_or_404(CategoryGroup, pk=pk, user__in=product_user_ids)
    group.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_category_groups")
    messages.success(request, "Category group deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def save_attribute_inline(request):
    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)

    attribute_id_raw = payload.get("id")
    attribute_instance = None
    if attribute_id_raw:
        try:
            attribute_pk = int(attribute_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid attribute identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        attribute_instance = get_object_or_404(CategoryAttribute, pk=attribute_pk, user__in=product_user_ids)

    def _normalize(value, default=""):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip()

    def _normalize_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    form_data = {
        "name": _normalize(payload.get("name", "")),
        "description": _normalize(payload.get("description", "")),
        "value_unit": _normalize(payload.get("value_unit", "")),
        "category": _normalize(payload.get("category_id", payload.get("category")), None),
        "attribute_type": _normalize(payload.get("attribute_type", "select")),
        "is_filterable": _normalize_bool(payload.get("is_filterable"), True),
        "is_comparable": _normalize_bool(payload.get("is_comparable"), False),
        "sort_order": _normalize(payload.get("sort_order", 0), 0),
        "is_active": _normalize_bool(payload.get("is_active"), True),
    }
    form = CategoryAttributeForm(form_data, instance=attribute_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    attribute = form.save(commit=False)
    if not attribute.user_id:
        attribute.user = request.user
    attribute.save()

    options_raw = payload.get("options", "") or ""
    option_values = [opt.strip() for opt in re.split(r"[\n,]+", str(options_raw)) if opt.strip()]

    if attribute.attribute_type == "select":
        existing_options = {option.value.lower(): option for option in attribute.options.all()}
        seen_keys = set()
        for idx, value in enumerate(option_values):
            key = value.lower()
            seen_keys.add(key)
            option = existing_options.get(key)
            if option:
                option.value = value
                option.sort_order = idx
                option.is_active = True
                option.save()
            else:
                CategoryAttributeOption.objects.create(
                    attribute=attribute,
                    value=value,
                    sort_order=idx,
                    is_active=True,
                )
        for key, option in existing_options.items():
            if key not in seen_keys and option.is_active:
                option.is_active = False
                option.save(update_fields=["is_active"])
    else:
        attribute.options.filter(is_active=True).update(is_active=False)

    response_data = {
        "attribute": {
            "id": attribute.pk,
            "name": attribute.name,
            "description": attribute.description or "",
            "value_unit": attribute.value_unit or "",
            "category": {
                "id": attribute.category_id,
                "name": attribute.category.name if attribute.category else "",
            },
            "attribute_type": attribute.attribute_type,
            "is_filterable": attribute.is_filterable,
            "is_comparable": attribute.is_comparable,
            "sort_order": attribute.sort_order,
            "is_active": attribute.is_active,
            "options": [option.value for option in attribute.options.filter(is_active=True).order_by("sort_order", "value")],
        }
    }
    status_code = 200 if attribute_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_attribute(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    attribute = get_object_or_404(CategoryAttribute, pk=pk, user__in=product_user_ids)
    attribute.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_attributes")
    messages.success(request, "Attribute deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def save_brand_inline(request):
    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)

    brand_id_raw = payload.get("id")
    brand_instance = None
    if brand_id_raw:
        try:
            brand_pk = int(brand_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid brand identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        brand_instance = get_object_or_404(ProductBrand, pk=brand_pk, user__in=product_user_ids)

    def _normalize(value, default=""):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip()

    def _normalize_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    form_data = {
        "name": _normalize(payload.get("name", "")),
        "description": _normalize(payload.get("description", "")),
        "sort_order": _normalize(payload.get("sort_order", 0), 0),
        "is_active": _normalize_bool(payload.get("is_active"), True),
    }
    form = ProductBrandForm(form_data, files=request.FILES, instance=brand_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    brand = form.save(commit=False)
    if not brand.user_id:
        brand.user = request.user
    brand.save()

    response_data = {
        "brand": {
            "id": brand.pk,
            "name": brand.name,
            "description": brand.description or "",
            "sort_order": brand.sort_order,
            "is_active": brand.is_active,
            "logo_url": brand.logo.url if brand.logo else "",
        }
    }
    status_code = 200 if brand_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_brand(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    brand = get_object_or_404(ProductBrand, pk=pk, user__in=product_user_ids)
    brand.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_brands")
    messages.success(request, "Brand deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def save_model_inline(request):
    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)

    model_id_raw = payload.get("id")
    model_instance = None
    if model_id_raw:
        try:
            model_pk = int(model_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid model identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        model_instance = get_object_or_404(ProductModel, pk=model_pk, user__in=product_user_ids)

    def _normalize(value, default=""):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip()

    def _normalize_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    form_data = {
        "name": _normalize(payload.get("name", "")),
        "description": _normalize(payload.get("description", "")),
        "brand": _normalize(payload.get("brand_id", payload.get("brand")), None),
        "year_start": _normalize(payload.get("year_start", "")),
        "year_end": _normalize(payload.get("year_end", "")),
        "sort_order": _normalize(payload.get("sort_order", 0), 0),
        "is_active": _normalize_bool(payload.get("is_active"), True),
    }
    form = ProductModelForm(form_data, instance=model_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    model = form.save(commit=False)
    if not model.user_id:
        model.user = request.user
    model.save()

    response_data = {
        "model": {
            "id": model.pk,
            "name": model.name,
            "description": model.description or "",
            "brand": {
                "id": model.brand_id,
                "name": model.brand.name if model.brand else "",
            },
            "year_start": model.year_start,
            "year_end": model.year_end,
            "sort_order": model.sort_order,
            "is_active": model.is_active,
        }
    }
    status_code = 200 if model_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_model(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    model = get_object_or_404(ProductModel, pk=pk, user__in=product_user_ids)
    model.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_models")
    messages.success(request, "Model deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def save_vin_inline(request):
    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)

    vin_id_raw = payload.get("id")
    vin_instance = None
    if vin_id_raw:
        try:
            vin_pk = int(vin_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid VIN identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        vin_instance = get_object_or_404(ProductVin, pk=vin_pk, user__in=product_user_ids)

    def _normalize(value, default=""):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip()

    def _normalize_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        return default

    form_data = {
        "vin": _normalize(payload.get("vin", "")),
        "description": _normalize(payload.get("description", "")),
        "sort_order": _normalize(payload.get("sort_order", 0), 0),
        "is_active": _normalize_bool(payload.get("is_active"), True),
    }
    form = ProductVinForm(form_data, instance=vin_instance, user=request.user)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    vin = form.save(commit=False)
    if not vin.user_id:
        vin.user = request.user
    vin.save()

    response_data = {
        "vin": {
            "id": vin.pk,
            "vin": vin.vin,
            "description": vin.description or "",
            "sort_order": vin.sort_order,
            "is_active": vin.is_active,
        }
    }
    status_code = 200 if vin_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def delete_vin(request, pk):
    product_user_ids = _get_inventory_user_ids(request)
    vin = get_object_or_404(ProductVin, pk=pk, user__in=product_user_ids)
    vin.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_vins")
    messages.success(request, "VIN deleted successfully.")
    return redirect(next_url)


##############################
# Product CRUD               #
##############################
def _serialize_product(product, *, stock_user_ids=None):
    stock_visible = True
    if stock_user_ids is not None:
        stock_visible = product.user_id in stock_user_ids
    quantity_in_stock = product.quantity_in_stock if stock_visible else ""
    reorder_level = product.reorder_level if stock_visible else ""
    return {
        "id": product.pk,
        "name": product.name,
        "sku": product.sku or "",
        "description": product.description or "",
        "category": {
            "id": product.category_id,
            "name": product.category.name if product.category else "",
        },
        "supplier": {
            "id": product.supplier_id,
            "name": product.supplier.name if product.supplier else "",
        },
        "brand": {
            "id": product.brand_id,
            "name": product.brand.name if product.brand else "",
        },
        "vehicle_model": {
            "id": product.vehicle_model_id,
            "name": product.vehicle_model.name if product.vehicle_model else "",
        },
        "vin_number": {
            "id": product.vin_number_id,
            "vin": product.vin_number.vin if product.vin_number else "",
        },
        "cost_price": str(product.cost_price) if product.cost_price is not None else "",
        "sale_price": str(product.sale_price) if product.sale_price is not None else "",
        "quantity_in_stock": quantity_in_stock,
        "reorder_level": reorder_level,
        "stock_visible": stock_visible,
        "item_type": product.item_type,
        "location": product.location or "",
        "image_url": product.image.url if product.image else "",
    }


@login_required
@require_POST
def save_product_inline(request):
    """Create or update a product via inline editing."""

    payload = None
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    elif request.POST:
        payload = request.POST
    elif request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid data submitted."}, status=400)
    else:
        payload = {}

    def _normalize(value, default=""):
        if value is None:
            return default
        return str(value).strip() if isinstance(value, str) else str(value)

    def _normalize_quantity(value):
        if value in (None, ""):
            return "0"
        return _normalize(value)

    product_id_raw = payload.get("id")
    product_instance = None
    if product_id_raw:
        try:
            product_pk = int(product_id_raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid product identifier provided."}, status=400)
        product_user_ids = _get_inventory_user_ids(request)
        product_instance = get_object_or_404(Product, pk=product_pk, user__in=product_user_ids)
    stock_user_ids = _get_inventory_stock_user_ids(request)
    stock_editable = True
    if product_instance and product_instance.user_id not in stock_user_ids:
        stock_editable = False

    item_type = (payload.get("item_type") or "inventory").strip()
    item_type_choices = dict(Product._meta.get_field("item_type").choices)
    if item_type not in item_type_choices:
        item_type = "inventory"

    quantity_raw = payload.get("quantity_in_stock")
    reorder_raw = payload.get("reorder_level")
    if product_instance and not stock_editable:
        quantity_raw = product_instance.quantity_in_stock or 0
        reorder_raw = product_instance.reorder_level or 0
    form_data = {
        "name": _normalize(payload.get("name")),
        "sku": _normalize(payload.get("sku")),
        "description": _normalize(payload.get("description")),
        "category": _normalize(payload.get("category_id")),
        "supplier": _normalize(payload.get("supplier_id")),
        "brand": _normalize(payload.get("brand_id", payload.get("brand"))),
        "vehicle_model": _normalize(payload.get("vehicle_model_id", payload.get("vehicle_model"))),
        "vin_number": _normalize(payload.get("vin_number_id", payload.get("vin_number"))),
        "cost_price": _normalize(payload.get("cost_price")),
        "sale_price": _normalize(payload.get("sale_price")),
        "quantity_in_stock": _normalize_quantity(quantity_raw),
        "reorder_level": _normalize_quantity(reorder_raw),
        "item_type": item_type,
        "location": _normalize(payload.get("location")),
    }

    form = ProductInlineForm(
        form_data,
        files=request.FILES,
        instance=product_instance,
        user=request.user,
    )
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    product = form.save(commit=False)
    if not product.user_id:
        product.user = request.user
    product.save()

    response_data = {"product": _serialize_product(product, stock_user_ids=stock_user_ids)}
    status_code = 200 if product_instance else 201
    return JsonResponse(response_data, status=status_code)


@login_required
@require_POST
def bulk_update_products(request):
    product_ids = _extract_ids(request.POST.getlist("product_ids"))
    if not product_ids:
        return JsonResponse({"error": "Select at least one product to update."}, status=400)

    stock_user_ids = _get_inventory_stock_user_ids(request)
    products = list(
        Product.objects.filter(
            user__in=_get_inventory_user_ids(request),
            id__in=product_ids,
        ).select_related(
            "category",
            "supplier",
            "brand",
            "vehicle_model",
            "vin_number",
        )
    )
    if not products:
        return JsonResponse({"error": "No matching products found."}, status=404)

    found_ids = {product.id for product in products}
    missing_ids = [pid for pid in product_ids if pid not in found_ids]
    if missing_ids:
        return JsonResponse({"error": "Some selected products were not found."}, status=404)

    field_map = {
        "category_id": "category",
        "supplier_id": "supplier",
        "brand_id": "brand",
        "vehicle_model_id": "vehicle_model",
        "vin_number_id": "vin_number",
        "item_type": "item_type",
        "location": "location",
        "description": "description",
        "cost_price": "cost_price",
        "sale_price": "sale_price",
        "quantity_in_stock": "quantity_in_stock",
        "reorder_level": "reorder_level",
    }

    updates = {}
    for request_key, field_name in field_map.items():
        if request_key not in request.POST:
            continue
        value = request.POST.get(request_key)
        if value == "__keep__":
            continue
        updates[field_name] = value

    if "item_type" in updates:
        item_type = updates["item_type"]
        valid_item_types = dict(Product._meta.get_field("item_type").choices)
        if item_type not in valid_item_types:
            return JsonResponse({"error": "Invalid item type selected."}, status=400)

    image_file = request.FILES.get("image")
    if not updates and not image_file:
        return JsonResponse({"error": "Choose at least one field to update."}, status=400)

    def _product_form_data(product):
        return {
            "name": product.name or "",
            "sku": product.sku or "",
            "description": product.description or "",
            "category": product.category_id or "",
            "supplier": product.supplier_id or "",
            "brand": product.brand_id or "",
            "vehicle_model": product.vehicle_model_id or "",
            "vin_number": product.vin_number_id or "",
            "cost_price": str(product.cost_price) if product.cost_price is not None else "",
            "sale_price": str(product.sale_price) if product.sale_price is not None else "",
            "quantity_in_stock": (
                str(product.quantity_in_stock) if product.quantity_in_stock is not None else "0"
            ),
            "reorder_level": str(product.reorder_level) if product.reorder_level is not None else "0",
            "item_type": product.item_type or "inventory",
            "location": product.location or "",
        }

    errors = {}
    updated_products = []
    try:
        with transaction.atomic():
            for product in products:
                base_data = _product_form_data(product)
                form_data = base_data.copy()
                form_data.update(updates)
                if product.user_id not in stock_user_ids:
                    form_data["quantity_in_stock"] = base_data.get("quantity_in_stock", "0")
                    form_data["reorder_level"] = base_data.get("reorder_level", "0")
                files = None
                if image_file:
                    image_file.seek(0)
                    files = {"image": image_file}
                form = ProductInlineForm(
                    form_data,
                    files=files,
                    instance=product,
                    user=request.user,
                )
                if not form.is_valid():
                    errors[product.pk] = form.errors
                    raise ValidationError("Bulk update failed.")
                updated_product = form.save(commit=False)
                if not updated_product.user_id:
                    updated_product.user = request.user
                updated_product.save()
                updated_products.append(updated_product)
    except ValidationError:
        error_payload = errors or {"__all__": ["Could not update selected products."]}
        return JsonResponse({"errors": error_payload}, status=400)

    return JsonResponse(
        {"products": [_serialize_product(product, stock_user_ids=stock_user_ids) for product in updated_products]}
    )

@login_required
def add_product(request):
    next_url = request.POST.get("next") or request.GET.get("next") or (reverse("accounts:inventory_products"))
    if request.method == "POST":
        form = ProductForm(user=request.user, data=request.POST, files=request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.user = request.user
            product.save()
            form.save_attribute_values(product)
            messages.success(request, "Product added successfully.")
        else:
            messages.error(
                request, "Error adding product. Please check the form for errors."
            )
    # Return to Products tab
    return redirect(next_url)


@login_required
@require_POST
def update_inventory_margin(request):
    profile = getattr(request.user, "profile", None)
    if not profile:
        messages.error(request, "No profile found for the current user.")
        return redirect(reverse("accounts:inventory_products"))

    margin_input = request.POST.get("default_margin_percent", "").strip()
    if margin_input == "":
        messages.error(request, "Enter a margin percentage before saving.")
        return redirect(reverse("accounts:inventory_products"))

    try:
        margin_value = Decimal(margin_input)
    except (InvalidOperation, TypeError):
        messages.error(request, "Invalid margin percentage.")
        return redirect(reverse("accounts:inventory_products"))

    if margin_value < Decimal("0"):
        messages.error(request, "Margin percentage cannot be negative.")
        return redirect(reverse("accounts:inventory_products"))

    margin_value = margin_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    profile.default_inventory_margin_percent = margin_value
    profile.save(update_fields=["default_inventory_margin_percent"])
    messages.success(request, "Default margin updated successfully.")
    return redirect(reverse("accounts:inventory_products"))


@login_required
@require_POST
def apply_margin_to_products(request):
    profile = getattr(request.user, "profile", None)
    if not profile:
        messages.error(request, "No profile found for the current user.")
        return redirect(reverse("accounts:inventory_products"))

    margin_percent = profile.default_inventory_margin_percent
    if margin_percent is None:
        messages.error(request, "Set a default margin before running the update.")
        return redirect(reverse("accounts:inventory_products"))

    updated_count = 0
    products = Product.objects.filter(
        user__in=_get_inventory_user_ids(request)
    ).exclude(cost_price__isnull=True)
    for product in products:
        product.sale_price = None
        product.margin = None
        product.save()
        updated_count += 1

    messages.success(
        request,
        f"Updated sale prices for {updated_count} product(s) using the {margin_percent}% margin.",
    )
    return redirect(reverse("accounts:inventory_products"))


@login_required
def edit_product(request):
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        product = get_object_or_404(
            Product,
            id=product_id,
            user__in=_get_inventory_user_ids(request),
        )
        form_data = request.POST.copy()
        stock_user_ids = _get_inventory_stock_user_ids(request)
        if product.user_id not in stock_user_ids:
            form_data["quantity_in_stock"] = str(product.quantity_in_stock or 0)
            form_data["reorder_level"] = str(product.reorder_level or 0)
        form = ProductForm(user=request.user, data=form_data, files=request.FILES, instance=product)
        if form.is_valid():
            product = form.save()
            form.save_attribute_values(product)
            messages.success(request, "Product updated successfully.")
        else:
            error_details = []
            for field_name, errors in form.errors.items():
                if field_name == "__all__":
                    label = "General"
                else:
                    label = form.fields.get(field_name).label or field_name.replace("_", " ").title()

                for error in errors:
                    error_details.append(f"{label}: {error}")

            if not error_details:
                error_details.append("Please check the form for errors.")

            detailed_message = "Error updating product. " + "; ".join(error_details)
            messages.error(request, detailed_message)
    # Return to Products tab
    return redirect(reverse("accounts:inventory_products"))


@login_required
@require_POST
def update_product_attributes(request):
    product_id = request.POST.get("product_id")
    if not product_id:
        messages.error(request, "Product ID not provided.")
        return redirect(reverse("accounts:inventory_products"))

    product = get_object_or_404(
        Product,
        id=product_id,
        user__in=_get_inventory_user_ids(request),
    )
    form = ProductAttributeForm(user=request.user, data=request.POST, instance=product)
    if form.is_valid():
        product = form.save()
        form.save_attribute_values(product)
        messages.success(request, "Product attributes updated successfully.")
    else:
        error_details = []
        for field_name, errors in form.errors.items():
            if field_name == "__all__":
                label = "General"
            else:
                label = form.fields.get(field_name).label or field_name.replace("_", " ").title()

            for error in errors:
                error_details.append(f"{label}: {error}")

        if not error_details:
            error_details.append("Please check the form for errors.")

        detailed_message = "Error updating product attributes. " + "; ".join(error_details)
        messages.error(request, detailed_message)

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_products")
    return redirect(next_url)


@login_required
def delete_product(request):
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        product = get_object_or_404(
            Product,
            id=product_id,
            user__in=_get_inventory_user_ids(request),
        )
        product.delete()
        messages.success(request, "Product deleted successfully.")
    else:
        messages.error(request, "Invalid request method.")
    # Return to Products tab
    return redirect(next_url)


@login_required
@require_POST
def delete_inventory_product(request, pk):
    product = get_object_or_404(
        Product,
        pk=pk,
        user__in=_get_inventory_user_ids(request),
    )
    product.delete()

    if _is_ajax(request) or "application/json" in (request.headers.get("Accept", "") or ""):
        return JsonResponse({"deleted": True})

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_products")
    messages.success(request, "Product deleted successfully.")
    return redirect(next_url)


@login_required
@require_POST
def bulk_delete_products(request):
    product_ids = _extract_ids(request.POST.getlist("product_ids"))
    if not product_ids:
        messages.warning(request, "No products were selected for deletion.")
        return redirect(reverse("accounts:inventory_products"))

    queryset = Product.objects.filter(
        user__in=_get_inventory_user_ids(request),
        id__in=product_ids,
    )
    deleted_count = queryset.count()

    if not deleted_count:
        messages.warning(request, "No matching products were found to delete.")
    else:
        queryset.delete()
        messages.success(request, f"Deleted {deleted_count} product(s).")

    return redirect(reverse("accounts:inventory_products"))


@login_required
def export_products_template(request):
    """Download an Excel template populated with the user's current products."""

    product_user_ids = _get_inventory_user_ids(request)
    stock_user_ids = _get_inventory_stock_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Products"

    instruction_text = (
        "Instructions: Enter warranty expiry dates using the YYYY-MM-DD format. "
        "Leave 'Warranty Length (Days)' blank so the system calculates remaining "
        "warranty days automatically. Provide both cost and sale prices or include "
        "the margin with one of the prices so missing values can be derived. Use "
        "Item Type values of Inventory or Non-inventory. Use Yes/No for Show on "
        "Storefront and Featured."
    )
    instruction_row = [instruction_text] + [""] * (len(PRODUCT_TEMPLATE_HEADERS) - 1)
    worksheet.append(instruction_row)
    worksheet.merge_cells(
        start_row=1,
        start_column=1,
        end_row=1,
        end_column=len(PRODUCT_TEMPLATE_HEADERS),
    )
    worksheet.append(PRODUCT_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A3"

    item_type_labels = dict(Product._meta.get_field("item_type").choices)
    products = Product.objects.filter(user__in=product_user_ids).order_by("name")
    for product in products:
        stock_visible = product.user_id in stock_user_ids
        quantity_value = product.quantity_in_stock if stock_visible else ""
        reorder_value = product.reorder_level if stock_visible else ""
        if product.margin is not None:
            margin_value = str(product.margin)
        elif product.cost_price is not None and product.sale_price is not None:
            margin_value = str(product.sale_price - product.cost_price)
        else:
            margin_value = ""
        item_type_label = item_type_labels.get(product.item_type, product.item_type)
        worksheet.append(
            [
                product.sku or "",
                product.name or "",
                product.description or "",
                product.category.name if product.category else "",
                product.supplier.name if product.supplier else "",
                product.brand.name if product.brand else "",
                product.vehicle_model.name if product.vehicle_model else "",
                product.vin_number.vin if product.vin_number else "",
                item_type_label or "",
                str(product.cost_price) if product.cost_price is not None else "",
                str(product.sale_price) if product.sale_price is not None else "",
                str(product.promotion_price) if product.promotion_price is not None else "",
                margin_value,
                quantity_value,
                reorder_value,
                product.location or "",
                product.warranty_expiry_date.isoformat()
                if product.warranty_expiry_date
                else "",
                product.warranty_length or "",
                "Yes" if product.is_published_to_store else "No",
                "Yes" if product.is_featured else "No",
            ]
        )

    categories = list(
        dict.fromkeys(
            Category.objects.filter(user__in=product_user_ids)
            .order_by("name")
            .values_list("name", flat=True)
        )
    )
    suppliers = list(
        dict.fromkeys(
            Supplier.objects.filter(user__in=product_user_ids)
            .order_by("name")
            .values_list("name", flat=True)
        )
    )
    brands = list(
        dict.fromkeys(
            ProductBrand.objects.filter(user__in=product_user_ids)
            .order_by("sort_order", "name")
            .values_list("name", flat=True)
        )
    )
    models = list(
        dict.fromkeys(
            ProductModel.objects.filter(user__in=product_user_ids)
            .order_by("sort_order", "name")
            .values_list("name", flat=True)
        )
    )
    vins = list(
        dict.fromkeys(
            ProductVin.objects.filter(user__in=product_user_ids)
            .order_by("sort_order", "vin")
            .values_list("vin", flat=True)
        )
    )

    product_locations = (
        Product.objects.filter(user__in=product_user_ids)
        .exclude(location__isnull=True)
        .exclude(location__exact="")
        .values_list("location", flat=True)
    )
    location_sources = list(
        InventoryLocation.objects.filter(user__in=product_user_ids)
        .order_by("name")
        .values_list("name", flat=True)
    )
    cleaned_product_locations = [loc.strip() for loc in product_locations if loc and loc.strip()]
    locations = list(dict.fromkeys(location_sources + cleaned_product_locations))
    item_types = [label for _value, label in Product._meta.get_field("item_type").choices]
    yes_no = ["Yes", "No"]

    options_sheet = workbook.create_sheet(title="Options")
    options_sheet.sheet_state = "hidden"

    def _write_option_column(column_index, header, values):
        options_sheet.cell(row=1, column=column_index, value=header)
        for row_index, value in enumerate(values, start=2):
            options_sheet.cell(row=row_index, column=column_index, value=value)
        last_row = max(2, len(values) + 1)
        column_letter = get_column_letter(column_index)
        return f"=Options!${column_letter}$2:${column_letter}${last_row}"

    category_formula = _write_option_column(1, "Categories", categories)
    supplier_formula = _write_option_column(2, "Suppliers", suppliers)
    location_formula = _write_option_column(3, "Locations", locations)
    brand_formula = _write_option_column(4, "Brands", brands)
    model_formula = _write_option_column(5, "Models", models)
    vin_formula = _write_option_column(6, "VINs", vins)
    item_type_formula = _write_option_column(7, "Item Types", item_types)
    yes_no_formula = _write_option_column(8, "Yes/No", yes_no)

    def _apply_validation(target_header, formula):
        target_column_index = PRODUCT_TEMPLATE_HEADERS.index(target_header) + 1
        target_column_letter = get_column_letter(target_column_index)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        worksheet.add_data_validation(validation)
        validation.add(f"{target_column_letter}2:{target_column_letter}1048576")

    _apply_validation("Category", category_formula)
    _apply_validation("Supplier", supplier_formula)
    _apply_validation("Location", location_formula)
    _apply_validation("Brand", brand_formula)
    _apply_validation("Model", model_formula)
    _apply_validation("VIN", vin_formula)
    _apply_validation("Item Type", item_type_formula)
    _apply_validation("Show on Storefront", yes_no_formula)
    _apply_validation("Featured", yes_no_formula)

    apply_template_styling(
        worksheet,
        headers=PRODUCT_TEMPLATE_HEADERS,
        header_row_index=2,
        instruction_row_index=1,
        column_width_overrides={
            "SKU": 18,
            "Name": 30,
            "Description": 48,
            "Category": 24,
            "Supplier": 24,
            "Brand": 20,
            "Model": 20,
            "VIN": 20,
            "Item Type": 16,
            "Cost Price": 16,
            "Sale Price": 16,
            "Promotion Price": 18,
            "Margin": 14,
            "Quantity": 14,
            "Reorder Level": 18,
            "Location": 22,
            "Warranty Expiry Date": 24,
            "Warranty Length (Days)": 26,
            "Show on Storefront": 20,
            "Featured": 14,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="products_template.xlsx"'
    return response


@login_required
def export_suppliers_template(request):
    """Download an Excel template populated with the user's current suppliers."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Suppliers"
    worksheet.append(SUPPLIER_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    suppliers = Supplier.objects.filter(user__in=product_user_ids).order_by("name")
    for supplier in suppliers:
        worksheet.append(
            [
                supplier.name or "",
                supplier.contact_person or "",
                supplier.email or "",
                supplier.phone_number or "",
                supplier.address or "",
            ]
        )

    apply_template_styling(
        worksheet,
        headers=SUPPLIER_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={
            "Name": 32,
            "Contact Person": 28,
            "Email": 36,
            "Phone Number": 22,
            "Address": 42,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="suppliers_template.xlsx"'
    return response


@login_required
def export_categories_template(request):
    """Download an Excel template populated with the user's current categories."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Categories"
    worksheet.append(CATEGORY_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    categories = Category.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    for category in categories:
        worksheet.append([
            category.name or "",
            category.description or "",
            category.group.name if category.group else "",
            category.parent.name if category.parent else "",
            category.sort_order,
            "Active" if category.is_active else "Inactive",
        ])

    groups = list(
        dict.fromkeys(
            CategoryGroup.objects.filter(user__in=product_user_ids)
            .order_by("sort_order", "name")
            .values_list("name", flat=True)
        )
    )
    parent_categories = list(
        dict.fromkeys(
            categories.values_list("name", flat=True)
        )
    )
    active_states = ["Active", "Inactive"]

    options_sheet = workbook.create_sheet(title="Options")
    options_sheet.sheet_state = "hidden"

    def _write_option_column(column_index, header, values):
        options_sheet.cell(row=1, column=column_index, value=header)
        for row_index, value in enumerate(values, start=2):
            options_sheet.cell(row=row_index, column=column_index, value=value)
        last_row = max(2, len(values) + 1)
        column_letter = get_column_letter(column_index)
        return f"=Options!${column_letter}$2:${column_letter}${last_row}"

    group_formula = _write_option_column(1, "Groups", groups)
    parent_formula = _write_option_column(2, "Parent Categories", parent_categories)
    active_formula = _write_option_column(3, "Active", active_states)

    def _apply_validation(target_header, formula):
        target_column_index = CATEGORY_TEMPLATE_HEADERS.index(target_header) + 1
        target_column_letter = get_column_letter(target_column_index)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        worksheet.add_data_validation(validation)
        validation.add(f"{target_column_letter}2:{target_column_letter}1048576")

    _apply_validation("Group", group_formula)
    _apply_validation("Parent Category", parent_formula)
    _apply_validation("Active", active_formula)

    apply_template_styling(
        worksheet,
        headers=CATEGORY_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={
            "Name": 32,
            "Description": 48,
            "Group": 24,
            "Parent Category": 24,
            "Sort Order": 14,
            "Active": 12,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="categories_template.xlsx"'
    return response


@login_required
def export_category_groups_template(request):
    """Download an Excel template populated with the user's current category groups."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Category Groups"
    worksheet.append(CATEGORY_GROUP_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    groups = CategoryGroup.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    for group in groups:
        worksheet.append([
            group.name or "",
            group.description or "",
            group.sort_order,
            "Active" if group.is_active else "Inactive",
        ])

    active_states = ["Active", "Inactive"]
    options_sheet = workbook.create_sheet(title="Options")
    options_sheet.sheet_state = "hidden"

    def _write_option_column(column_index, header, values):
        options_sheet.cell(row=1, column=column_index, value=header)
        for row_index, value in enumerate(values, start=2):
            options_sheet.cell(row=row_index, column=column_index, value=value)
        last_row = max(2, len(values) + 1)
        column_letter = get_column_letter(column_index)
        return f"=Options!${column_letter}$2:${column_letter}${last_row}"

    active_formula = _write_option_column(1, "Active", active_states)

    def _apply_validation(target_header, formula):
        target_column_index = CATEGORY_GROUP_TEMPLATE_HEADERS.index(target_header) + 1
        target_column_letter = get_column_letter(target_column_index)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        worksheet.add_data_validation(validation)
        validation.add(f"{target_column_letter}2:{target_column_letter}1048576")

    _apply_validation("Active", active_formula)

    apply_template_styling(
        worksheet,
        headers=CATEGORY_GROUP_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={
            "Name": 32,
            "Description": 48,
            "Sort Order": 14,
            "Active": 12,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="category_groups_template.xlsx"'
    return response


@login_required
def export_brands_template(request):
    """Download an Excel template populated with the user's current brands."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Brands"
    worksheet.append(BRAND_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    brands = ProductBrand.objects.filter(user__in=product_user_ids).order_by("sort_order", "name")
    for brand in brands:
        worksheet.append([
            brand.name or "",
            brand.description or "",
            brand.sort_order,
            "Active" if brand.is_active else "Inactive",
        ])

    active_states = ["Active", "Inactive"]
    options_sheet = workbook.create_sheet(title="Options")
    options_sheet.sheet_state = "hidden"

    def _write_option_column(column_index, header, values):
        options_sheet.cell(row=1, column=column_index, value=header)
        for row_index, value in enumerate(values, start=2):
            options_sheet.cell(row=row_index, column=column_index, value=value)
        last_row = max(2, len(values) + 1)
        column_letter = get_column_letter(column_index)
        return f"=Options!${column_letter}$2:${column_letter}${last_row}"

    active_formula = _write_option_column(1, "Active", active_states)

    def _apply_validation(target_header, formula):
        target_column_index = BRAND_TEMPLATE_HEADERS.index(target_header) + 1
        target_column_letter = get_column_letter(target_column_index)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        worksheet.add_data_validation(validation)
        validation.add(f"{target_column_letter}2:{target_column_letter}1048576")

    _apply_validation("Active", active_formula)

    apply_template_styling(
        worksheet,
        headers=BRAND_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={
            "Name": 32,
            "Description": 48,
            "Sort Order": 14,
            "Active": 12,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="brands_template.xlsx"'
    return response


@login_required
def export_models_template(request):
    """Download an Excel template populated with the user's current models."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Models"
    worksheet.append(MODEL_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    models = (
        ProductModel.objects.filter(user__in=product_user_ids)
        .select_related("brand")
        .order_by("sort_order", "name")
    )
    for model in models:
        worksheet.append([
            model.name or "",
            model.brand.name if model.brand else "",
            model.description or "",
            model.year_start or "",
            model.year_end or "",
            model.sort_order,
            "Active" if model.is_active else "Inactive",
        ])

    brand_names = list(
        dict.fromkeys(
            ProductBrand.objects.filter(user__in=product_user_ids)
            .order_by("sort_order", "name")
            .values_list("name", flat=True)
        )
    )
    active_states = ["Active", "Inactive"]
    options_sheet = workbook.create_sheet(title="Options")
    options_sheet.sheet_state = "hidden"

    def _write_option_column(column_index, header, values):
        options_sheet.cell(row=1, column=column_index, value=header)
        for row_index, value in enumerate(values, start=2):
            options_sheet.cell(row=row_index, column=column_index, value=value)
        last_row = max(2, len(values) + 1)
        column_letter = get_column_letter(column_index)
        return f"=Options!${column_letter}$2:${column_letter}${last_row}"

    brand_formula = _write_option_column(1, "Brands", brand_names)
    active_formula = _write_option_column(2, "Active", active_states)

    def _apply_validation(target_header, formula):
        target_column_index = MODEL_TEMPLATE_HEADERS.index(target_header) + 1
        target_column_letter = get_column_letter(target_column_index)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        worksheet.add_data_validation(validation)
        validation.add(f"{target_column_letter}2:{target_column_letter}1048576")

    _apply_validation("Brand", brand_formula)
    _apply_validation("Active", active_formula)

    apply_template_styling(
        worksheet,
        headers=MODEL_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={
            "Name": 28,
            "Brand": 24,
            "Description": 48,
            "Year Start": 14,
            "Year End": 14,
            "Sort Order": 14,
            "Active": 12,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="models_template.xlsx"'
    return response


@login_required
def export_vins_template(request):
    """Download an Excel template populated with the user's current VINs."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "VINs"
    worksheet.append(VIN_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    vins = ProductVin.objects.filter(user__in=product_user_ids).order_by("sort_order", "vin")
    for vin in vins:
        worksheet.append([
            vin.vin or "",
            vin.description or "",
            vin.sort_order,
            "Active" if vin.is_active else "Inactive",
        ])

    active_states = ["Active", "Inactive"]
    options_sheet = workbook.create_sheet(title="Options")
    options_sheet.sheet_state = "hidden"

    def _write_option_column(column_index, header, values):
        options_sheet.cell(row=1, column=column_index, value=header)
        for row_index, value in enumerate(values, start=2):
            options_sheet.cell(row=row_index, column=column_index, value=value)
        last_row = max(2, len(values) + 1)
        column_letter = get_column_letter(column_index)
        return f"=Options!${column_letter}$2:${column_letter}${last_row}"

    active_formula = _write_option_column(1, "Active", active_states)

    def _apply_validation(target_header, formula):
        target_column_index = VIN_TEMPLATE_HEADERS.index(target_header) + 1
        target_column_letter = get_column_letter(target_column_index)
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        worksheet.add_data_validation(validation)
        validation.add(f"{target_column_letter}2:{target_column_letter}1048576")

    _apply_validation("Active", active_formula)

    apply_template_styling(
        worksheet,
        headers=VIN_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={
            "VIN": 24,
            "Description": 48,
            "Sort Order": 14,
            "Active": 12,
        },
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="vins_template.xlsx"'
    return response


@login_required
def export_locations_template(request):
    """Download an Excel template populated with the user's current inventory locations."""

    product_user_ids = _get_inventory_user_ids(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Locations"
    worksheet.append(LOCATION_TEMPLATE_HEADERS)
    worksheet.freeze_panes = "A2"

    locations = InventoryLocation.objects.filter(user__in=product_user_ids).order_by("name")
    for location in locations:
        worksheet.append([location.name or ""])

    apply_template_styling(
        worksheet,
        headers=LOCATION_TEMPLATE_HEADERS,
        header_row_index=1,
        column_width_overrides={"Name": 34},
    )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="locations_template.xlsx"'
    return response


def _parse_decimal(value, field_name, allow_blank=True):
    if value in (None, ""):
        if allow_blank:
            return None
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc


def _parse_integer(value, field_name):
    if value in (None, ""):
        return 0
    try:
        decimal_value = Decimal(str(value))
        if decimal_value != decimal_value.to_integral_value():
            raise ValueError
        return int(decimal_value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def _parse_optional_integer(value, field_name):
    if value in (None, ""):
        return None
    return _parse_integer(value, field_name)


def _parse_date(value, field_name):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        raise ValueError(
            f"{field_name} must be a valid date in YYYY-MM-DD format."
        )
    raise ValueError(f"{field_name} must be a valid date.")


def _parse_boolean(value, field_name, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        truthy = {"1", "true", "yes", "y", "active", "enabled", "on"}
        falsy = {"0", "false", "no", "n", "inactive", "disabled", "off"}
        if normalized in truthy:
            return True
        if normalized in falsy:
            return False
    raise ValueError(f"{field_name} must be yes/no or true/false.")


@login_required
@require_POST
def import_products_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or (reverse("accounts:inventory_products"))
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active

    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in PRODUCT_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {header: headers.index(header) for header in PRODUCT_TEMPLATE_HEADERS}

    item_type_choices = Product._meta.get_field("item_type").choices
    item_type_map = {}
    for value, label in item_type_choices:
        item_type_map[str(value).strip().lower()] = value
        item_type_map[str(label).strip().lower()] = value
        item_type_map[str(label).strip().lower().replace("-", "_")] = value

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            sku = _normalize_text(get_value("SKU"))

            raw_name = get_value("Name")
            name = _normalize_text(raw_name)
            if not name:
                raise ValueError("Name is required.")

            description = get_value("Description") or ""
            if isinstance(description, str):
                description = description.strip()

            category_name = _normalize_text(get_value("Category"))
            category = None
            if category_name:
                category = Category.objects.filter(
                    user=request.user, name__iexact=category_name
                ).first()
                if not category:
                    category = Category.objects.create(
                        user=request.user,
                        name=category_name,
                        description="",
                    )

            supplier_name = _normalize_text(get_value("Supplier"))
            supplier = None
            if supplier_name:
                supplier = Supplier.objects.filter(
                    user=request.user, name__iexact=supplier_name
                ).first()
                if not supplier:
                    supplier = Supplier.objects.create(
                        user=request.user,
                        name=supplier_name,
                    )

            brand_name = _normalize_text(get_value("Brand"))
            brand = None
            if brand_name:
                brand = ProductBrand.objects.filter(
                    user=request.user, name__iexact=brand_name
                ).first()
                if not brand:
                    brand = ProductBrand.objects.create(
                        user=request.user,
                        name=brand_name,
                    )

            model_name = _normalize_text(get_value("Model"))
            vehicle_model = None
            if model_name:
                model_qs = ProductModel.objects.filter(
                    user=request.user, name__iexact=model_name
                )
                if brand:
                    model_qs = model_qs.filter(brand=brand)
                vehicle_model = model_qs.first()
                if not vehicle_model:
                    vehicle_model = ProductModel.objects.create(
                        user=request.user,
                        name=model_name,
                        brand=brand,
                    )

            vin_value = _normalize_text(get_value("VIN"))
            vin_number = None
            if vin_value:
                vin_number = ProductVin.objects.filter(
                    user=request.user, vin__iexact=vin_value
                ).first()
                if not vin_number:
                    vin_number = ProductVin.objects.create(
                        user=request.user,
                        vin=vin_value,
                    )

            cost_price = _parse_decimal(get_value("Cost Price"), "Cost Price")
            sale_price = _parse_decimal(get_value("Sale Price"), "Sale Price")
            promotion_price = _parse_decimal(get_value("Promotion Price"), "Promotion Price")
            margin = _parse_decimal(get_value("Margin"), "Margin")

            for label, value in (("Cost Price", cost_price), ("Sale Price", sale_price)):
                if value is not None and value < Decimal("0"):
                    raise ValueError(f"{label} cannot be negative.")
            if margin is None:
                if cost_price is None and sale_price is None:
                    raise ValueError(
                        "Provide Cost Price and Sale Price, or include the Margin so missing values can be calculated."
                    )
                if cost_price is None or sale_price is None:
                    raise ValueError(
                        "Margin is required when only one of Cost Price or Sale Price is supplied."
                    )
                margin = sale_price - cost_price
            else:
                if cost_price is None and sale_price is None:
                    raise ValueError(
                        "Cost Price or Sale Price is required when Margin is provided."
                    )
                if cost_price is None:
                    cost_price = sale_price - margin
                if sale_price is None:
                    sale_price = cost_price + margin
                if cost_price is not None and sale_price is not None:
                    margin = sale_price - cost_price

            if cost_price is None or sale_price is None:
                raise ValueError("Unable to determine both Cost Price and Sale Price from the provided values.")

            if cost_price < Decimal("0"):
                raise ValueError("Cost Price cannot be negative.")
            if sale_price < Decimal("0"):
                raise ValueError("Sale Price cannot be negative.")
            if promotion_price is not None and promotion_price < Decimal("0"):
                raise ValueError("Promotion Price cannot be negative.")

            quantity = _parse_integer(get_value("Quantity"), "Quantity")
            if quantity < 0:
                raise ValueError("Quantity cannot be negative.")

            reorder_level = _parse_integer(
                get_value("Reorder Level"), "Reorder Level"
            )
            if reorder_level < 0:
                raise ValueError("Reorder Level cannot be negative.")

            location = _normalize_text(get_value("Location"))

            warranty_expiry = _parse_date(
                get_value("Warranty Expiry Date"), "Warranty Expiry Date"
            )
            warranty_length = get_value("Warranty Length (Days)")
            if warranty_length in (None, ""):
                warranty_length_value = None
            else:
                warranty_length_value = _parse_integer(
                    warranty_length, "Warranty Length (Days)"
                )
                if warranty_length_value < 0:
                    raise ValueError("Warranty Length cannot be negative.")

            item_type_raw = _normalize_text(get_value("Item Type"))
            item_type = None
            if item_type_raw:
                normalized_item_type = item_type_raw.strip().lower().replace(" ", "_").replace("-", "_")
                item_type = item_type_map.get(normalized_item_type)
                if not item_type:
                    raise ValueError("Item Type must be Inventory or Non-inventory.")

            show_on_storefront = _parse_boolean(
                get_value("Show on Storefront"), "Show on Storefront", default=None
            )
            featured = _parse_boolean(get_value("Featured"), "Featured", default=None)

            product = None
            if sku:
                product = Product.objects.filter(
                    user=request.user, sku__iexact=sku
                ).first()
            if not product:
                product = Product.objects.filter(
                    user=request.user, name__iexact=name
                ).first()

            if product:
                is_new = False
            else:
                product = Product(user=request.user)
                is_new = True

            product.user = request.user
            product.sku = sku or None
            product.name = name
            product.description = description or ""
            product.category = category
            product.supplier = supplier
            product.brand = brand
            product.vehicle_model = vehicle_model
            product.vin_number = vin_number
            product.cost_price = cost_price
            product.sale_price = sale_price
            product.promotion_price = promotion_price
            product.margin = margin
            product.quantity_in_stock = quantity
            product.reorder_level = reorder_level
            product.location = location or ""
            product.warranty_expiry_date = warranty_expiry
            product.warranty_length = warranty_length_value
            if item_type:
                product.item_type = item_type
            if show_on_storefront is not None:
                product.is_published_to_store = show_on_storefront
            if featured is not None:
                product.is_featured = featured

            product.clean()
            product.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new product(s) and updated {updated_count} product(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(reverse("accounts:inventory_products"))


def _normalize_text(value):
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return ("%s" % value).strip()
    return str(value).strip()


def _extract_ids(raw_ids):
    valid_ids = []
    for value in raw_ids:
        try:
            valid_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return valid_ids


@login_required
@require_POST
def import_suppliers_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or (reverse("accounts:inventory_suppliers"))
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active
    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in SUPPLIER_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: " + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {header: headers.index(header) for header in SUPPLIER_TEMPLATE_HEADERS}

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            raw_name = get_value("Name")
            name = _normalize_text(raw_name)
            if not name:
                raise ValueError("Name is required.")

            contact_person = _normalize_text(get_value("Contact Person"))
            email_value = _normalize_text(get_value("Email"))
            phone_number = _normalize_text(get_value("Phone Number"))
            address = _normalize_text(get_value("Address"))

            supplier = Supplier.objects.filter(user=request.user, name__iexact=name).first()
            if supplier:
                is_new = False
            else:
                supplier = Supplier(user=request.user)
                is_new = True

            supplier.name = name
            supplier.contact_person = contact_person or None
            supplier.email = email_value or None
            supplier.phone_number = phone_number or None
            supplier.address = address or ""

            supplier.full_clean()
            supplier.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new supplier(s) and updated {updated_count} supplier(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(next_url)


@login_required
@require_POST
def import_categories_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or (reverse("accounts:inventory_categories"))
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active
    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in CATEGORY_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {header: headers.index(header) for header in CATEGORY_TEMPLATE_HEADERS}

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            name = _normalize_text(get_value("Name"))
            if not name:
                raise ValueError("Name is required.")

            description = _normalize_text(get_value("Description"))
            group_name = _normalize_text(get_value("Group"))
            parent_name = _normalize_text(get_value("Parent Category"))
            sort_order = _parse_integer(get_value("Sort Order"), "Sort Order")
            is_active = _parse_boolean(get_value("Active"), "Active", default=None)

            group = None
            if group_name:
                group = CategoryGroup.objects.filter(
                    user=request.user, name__iexact=group_name
                ).first()
                if not group:
                    group = CategoryGroup.objects.create(
                        user=request.user,
                        name=group_name,
                    )

            parent = None
            if parent_name and parent_name.lower() != name.lower():
                parent = Category.objects.filter(
                    user=request.user, name__iexact=parent_name
                ).first()
                if not parent:
                    parent = Category.objects.create(
                        user=request.user,
                        name=parent_name,
                        group=group,
                    )

            category = Category.objects.filter(
                user=request.user, name__iexact=name
            ).first()
            if category:
                is_new = False
            else:
                category = Category(user=request.user)
                is_new = True

            category.name = name
            category.description = description or ""
            category.group = group
            category.parent = parent
            category.sort_order = sort_order
            if is_active is not None:
                category.is_active = is_active
            if category.parent_id and category.parent_id == category.pk:
                category.parent = None
            category.full_clean()
            category.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new category(ies) and updated {updated_count} category(ies).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(next_url)


@login_required
@require_POST
def import_category_groups_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_category_groups")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active
    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in CATEGORY_GROUP_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {
        header: headers.index(header) for header in CATEGORY_GROUP_TEMPLATE_HEADERS
    }

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            name = _normalize_text(get_value("Name"))
            if not name:
                raise ValueError("Name is required.")

            description = _normalize_text(get_value("Description"))
            sort_order = _parse_integer(get_value("Sort Order"), "Sort Order")
            is_active = _parse_boolean(get_value("Active"), "Active", default=None)

            group = CategoryGroup.objects.filter(
                user=request.user, name__iexact=name
            ).first()
            if group:
                is_new = False
            else:
                group = CategoryGroup(user=request.user)
                is_new = True

            group.name = name
            group.description = description or ""
            group.sort_order = sort_order
            if is_active is not None:
                group.is_active = is_active

            group.full_clean()
            group.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new group(s) and updated {updated_count} group(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(next_url)


@login_required
@require_POST
def import_brands_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_brands")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active
    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in BRAND_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {header: headers.index(header) for header in BRAND_TEMPLATE_HEADERS}

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            name = _normalize_text(get_value("Name"))
            if not name:
                raise ValueError("Name is required.")

            description = _normalize_text(get_value("Description"))
            sort_order = _parse_integer(get_value("Sort Order"), "Sort Order")
            is_active = _parse_boolean(get_value("Active"), "Active", default=None)

            brand = ProductBrand.objects.filter(
                user=request.user, name__iexact=name
            ).first()
            if brand:
                is_new = False
            else:
                brand = ProductBrand(user=request.user)
                is_new = True

            brand.name = name
            brand.description = description or ""
            brand.sort_order = sort_order
            if is_active is not None:
                brand.is_active = is_active

            brand.full_clean()
            brand.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new brand(s) and updated {updated_count} brand(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(next_url)


@login_required
@require_POST
def import_models_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_models")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active
    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in MODEL_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {header: headers.index(header) for header in MODEL_TEMPLATE_HEADERS}

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            name = _normalize_text(get_value("Name"))
            if not name:
                raise ValueError("Name is required.")

            brand_name = _normalize_text(get_value("Brand"))
            description = _normalize_text(get_value("Description"))
            year_start = _parse_optional_integer(get_value("Year Start"), "Year Start")
            year_end = _parse_optional_integer(get_value("Year End"), "Year End")
            sort_order = _parse_integer(get_value("Sort Order"), "Sort Order")
            is_active = _parse_boolean(get_value("Active"), "Active", default=None)

            brand = None
            if brand_name:
                brand = ProductBrand.objects.filter(
                    user=request.user, name__iexact=brand_name
                ).first()
                if not brand:
                    brand = ProductBrand.objects.create(
                        user=request.user,
                        name=brand_name,
                    )

            model = ProductModel.objects.filter(
                user=request.user, name__iexact=name
            ).first()
            if model:
                is_new = False
            else:
                model = ProductModel(user=request.user)
                is_new = True

            model.name = name
            model.brand = brand
            model.description = description or ""
            model.year_start = year_start
            model.year_end = year_end
            model.sort_order = sort_order
            if is_active is not None:
                model.is_active = is_active

            model.full_clean()
            model.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new model(s) and updated {updated_count} model(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(next_url)


@login_required
@require_POST
def import_vins_from_excel(request):
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("accounts:inventory_vins")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(next_url)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(next_url)

    worksheet = workbook.active
    header_cells = None
    header_row_index = None
    for row in worksheet.iter_rows(min_row=1):
        row_values = [cell.value for cell in row]
        if not any(row_values):
            continue
        first_value = row_values[0]
        if isinstance(first_value, str) and first_value.startswith("Instructions:"):
            continue
        header_cells = row
        header_row_index = row[0].row
        break

    if header_cells is None:
        messages.error(request, "The uploaded file is empty or missing a header row.")
        return redirect(next_url)

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in VIN_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(next_url)

    header_indexes = {header: headers.index(header) for header in VIN_TEMPLATE_HEADERS}

    created_count = 0
    updated_count = 0
    errors = []

    data_start_row = header_row_index + 1
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            vin_value = _normalize_text(get_value("VIN"))
            if not vin_value:
                raise ValueError("VIN is required.")
            vin_value = vin_value.upper()

            description = _normalize_text(get_value("Description"))
            sort_order = _parse_integer(get_value("Sort Order"), "Sort Order")
            is_active = _parse_boolean(get_value("Active"), "Active", default=None)

            vin = ProductVin.objects.filter(
                user=request.user, vin__iexact=vin_value
            ).first()
            if vin:
                is_new = False
            else:
                vin = ProductVin(user=request.user)
                is_new = True

            vin.vin = vin_value
            vin.description = description or ""
            vin.sort_order = sort_order
            if is_active is not None:
                vin.is_active = is_active

            vin.full_clean()
            vin.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new VIN(s) and updated {updated_count} VIN(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(next_url)


@login_required
@require_POST
def import_locations_from_excel(request):
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Please select an Excel file to upload.")
        return redirect(reverse("accounts:inventory_locations"))

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded file. Please upload a valid .xlsx file.")
        return redirect(reverse("accounts:inventory_locations"))

    worksheet = workbook.active
    try:
        header_cells = next(worksheet.iter_rows(min_row=1, max_row=1))
    except StopIteration:
        messages.error(request, "The uploaded file is empty.")
        return redirect(reverse("accounts:inventory_locations"))

    headers = []
    for cell in header_cells:
        value = cell.value
        if isinstance(value, str):
            value = value.strip()
        headers.append(value or "")

    missing_headers = [h for h in LOCATION_TEMPLATE_HEADERS if h not in headers]
    if missing_headers:
        messages.error(
            request,
            "The uploaded file is missing required columns: "
            + ", ".join(missing_headers),
        )
        return redirect(reverse("accounts:inventory_locations"))

    header_indexes = {header: headers.index(header) for header in LOCATION_TEMPLATE_HEADERS}

    created_count = 0
    updated_count = 0
    errors = []

    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=2, values_only=True), start=2
    ):
        if not row or not any(row):
            continue

        def get_value(column_name):
            idx = header_indexes[column_name]
            return row[idx] if idx < len(row) else None

        try:
            name = _normalize_text(get_value("Name"))
            if not name:
                raise ValueError("Name is required.")

            location = InventoryLocation.objects.filter(
                user=request.user, name__iexact=name
            ).first()
            if location:
                is_new = False
            else:
                location = InventoryLocation(user=request.user)
                is_new = True

            location.name = name
            location.full_clean()
            location.save()

            if is_new:
                created_count += 1
            else:
                updated_count += 1

        except ValidationError as exc:
            errors.append(f"Row {row_index}: {exc.message}")
        except ValueError as exc:
            errors.append(f"Row {row_index}: {exc}")

    if created_count or updated_count:
        messages.success(
            request,
            f"Imported {created_count} new location(s) and updated {updated_count} location(s).",
        )

    if errors:
        error_preview = "; ".join(errors[:10])
        if len(errors) > 10:
            error_preview += f"; and {len(errors) - 10} more issue(s)."
        messages.warning(
            request,
            f"Some rows could not be imported: {error_preview}",
        )

    return redirect(reverse("accounts:inventory_locations"))


##############################
# Category CRUD              #
##############################
@login_required
def add_category(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if request.method == "POST":
        form = CategoryForm(request.POST, user=request.user)
        if form.is_valid():
            category = form.save(commit=False)
            category.user = request.user
            category.save()
            messages.success(request, "Category added successfully.")
            if _is_ajax(request):
                return JsonResponse(
                    {"success": True, "value": category.id, "label": category.name}
                )
        else:
            messages.error(
                request, "Error adding category. Please check the form for errors."
            )
            if _is_ajax(request):
                return JsonResponse(
                    {"success": False, "errors": _form_errors_json(form)}, status=400
                )
    return redirect(next_url or reverse("accounts:inventory_categories"))


@login_required
def edit_category(request):
    if request.method == "POST":
        category_id = request.POST.get("category_id")
        category = get_object_or_404(
            Category,
            id=category_id,
            user__in=_get_inventory_user_ids(request),
        )
        form = CategoryForm(request.POST, user=request.user, instance=category)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, "Category updated successfully.")
            except Exception as e:
                messages.error(request, "Error updating category: " + str(e))
        else:
            messages.error(
                request, "Error updating category. Please check the form for errors."
            )
    # Return to Categories tab
    return redirect(reverse("accounts:inventory_categories"))


@login_required
def delete_category(request):
    if request.method == "POST":
        category_id = request.POST.get("category_id")
        category = get_object_or_404(
            Category,
            id=category_id,
            user__in=_get_inventory_user_ids(request),
        )
        category.delete()
        messages.success(request, "Category deleted successfully.")
    else:
        messages.error(request, "Invalid request method.")
    # Return to Categories tab
    return redirect(reverse("accounts:inventory_categories"))


@login_required
@require_POST
def bulk_delete_categories(request):
    category_ids = _extract_ids(request.POST.getlist("category_ids"))
    if not category_ids:
        messages.warning(request, "No categories were selected for deletion.")
        return redirect(reverse("accounts:inventory_categories"))

    queryset = Category.objects.filter(
        user__in=_get_inventory_user_ids(request),
        id__in=category_ids,
    )
    deleted_count = queryset.count()

    if not deleted_count:
        messages.warning(request, "No matching categories were found to delete.")
    else:
        queryset.delete()
        messages.success(request, f"Deleted {deleted_count} category(ies).")

    return redirect(reverse("accounts:inventory_categories"))


##############################
# Location CRUD              #
##############################
@login_required
def add_location(request):
    next_url = request.POST.get("next") or request.GET.get("next") or (reverse("accounts:inventory_locations"))
    if request.method == "POST":
        form = InventoryLocationForm(request.POST, user=request.user)
        if form.is_valid():
            location = form.save(commit=False)
            location.user = request.user
            location.save()
            messages.success(request, "Location added successfully.")
            if _is_ajax(request):
                return JsonResponse(
                    {"success": True, "value": location.name, "label": location.name}
                )
        else:
            messages.error(
                request, "Error adding location. Please check the form for errors."
            )
            if _is_ajax(request):
                return JsonResponse(
                    {"success": False, "errors": _form_errors_json(form)}, status=400
                )
    return redirect(next_url)


@login_required
def edit_location(request):
    if request.method == "POST":
        location_id = request.POST.get("location_id")
        location = get_object_or_404(
            InventoryLocation,
            id=location_id,
            user__in=_get_inventory_user_ids(request),
        )
        form = InventoryLocationForm(request.POST, user=request.user, instance=location)
        if form.is_valid():
            form.save()
            messages.success(request, "Location updated successfully.")
        else:
            messages.error(
                request, "Error updating location. Please check the form for errors."
            )
    return redirect(reverse("accounts:inventory_locations"))


@login_required
def delete_location(request):
    if request.method == "POST":
        location_id = request.POST.get("location_id")
        location = get_object_or_404(
            InventoryLocation,
            id=location_id,
            user__in=_get_inventory_user_ids(request),
        )
        location.delete()
        messages.success(request, "Location deleted successfully.")
    else:
        messages.error(request, "Invalid request method.")
    return redirect(reverse("accounts:inventory_locations"))


@login_required
@require_POST
def bulk_delete_locations(request):
    location_ids = _extract_ids(request.POST.getlist("location_ids"))
    if not location_ids:
        messages.warning(request, "No locations were selected for deletion.")
        return redirect(reverse("accounts:inventory_locations"))

    queryset = InventoryLocation.objects.filter(
        user__in=_get_inventory_user_ids(request),
        id__in=location_ids,
    )
    deleted_count = queryset.count()

    if not deleted_count:
        messages.warning(request, "No matching locations were found to delete.")
    else:
        queryset.delete()
        messages.success(request, f"Deleted {deleted_count} location(s).")

    return redirect(reverse("accounts:inventory_locations"))


##############################
# QR Code & Stock-In Views    #
##############################


@login_required
def product_qr_pdf(request, product_id):
    product = get_object_or_404(
        Product,
        id=product_id,
        user__in=_get_inventory_user_ids(request),
    )
    stock_url = request.build_absolute_uri(
        reverse("accounts:qr_stock_in", args=[product.id])
    )

    try:
        profile = request.user.profile
        font_scale_percent = profile.qr_code_font_scale or 100
        show_name = profile.qr_show_name
        show_description = profile.qr_show_description
        show_sku = profile.qr_show_sku
    except (Profile.DoesNotExist, AttributeError):
        font_scale_percent = 100
        show_name = True
        show_description = True
        show_sku = True

    try:
        font_scale_percent = int(font_scale_percent)
    except (TypeError, ValueError):
        font_scale_percent = 100

    font_scale_percent = max(20, min(160, font_scale_percent))
    font_scale = font_scale_percent / 100.0

    img = qrcode.make(stock_url)
    if img.mode != "RGB":
        img = img.convert("RGB")

    dpi = 300
    label_width_in = 3.5
    label_height_in = 1.125
    label_width_px = int(round(label_width_in * dpi))
    label_height_px = int(round(label_height_in * dpi))

    label_image = Image.new("RGB", (label_width_px, label_height_px), "white")
    draw = ImageDraw.Draw(label_image)

    try:
        resampling = Image.Resampling.LANCZOS  # Pillow >= 9.1
    except AttributeError:  # pragma: no cover - Pillow < 9.1
        resampling = Image.LANCZOS

    qr_target_size = int(label_height_px * 0.9)
    qr_image = img.resize((qr_target_size, qr_target_size), resampling)

    vertical_center = (label_height_px - qr_target_size) // 2
    horizontal_padding = int(label_height_px * 0.1)
    label_image.paste(qr_image, (horizontal_padding, vertical_center))

    text_start_x = horizontal_padding + qr_target_size + horizontal_padding
    text_area_width = label_width_px - text_start_x - horizontal_padding
    top_padding = int(label_height_px * 0.1)
    bottom_padding = top_padding
    text_top = top_padding
    text_bottom_limit = label_height_px - bottom_padding
    text_color = (26, 26, 26)

    bold_font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    regular_font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    def load_font(size, bold=False):
        paths = bold_font_paths if bold else regular_font_paths
        for path in paths:
            if os.path.exists(path):
                return ImageFont.truetype(path, size=size)
        return ImageFont.load_default()

    def line_height(font):
        ascent, descent = font.getmetrics()
        return ascent + descent

    name_font = load_font(max(int(label_height_px * 0.28 * font_scale), 10), bold=True)
    description_font = load_font(max(int(label_height_px * 0.18 * font_scale), 8))
    sku_font = load_font(max(int(label_height_px * 0.16 * font_scale), 8))

    def wrap_text(text, font):
        if not text:
            return []
        lines = []
        words = text.split()
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            if draw.textlength(test_line, font=font) <= text_area_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    sku_reserved_height = line_height(sku_font) if show_sku and product.sku else 0
    available_text_bottom = max(text_top, text_bottom_limit - sku_reserved_height)

    current_y = text_top

    def draw_wrapped_lines(lines, font, fill, max_bottom):
        nonlocal current_y
        if not lines:
            return
        height = line_height(font)
        for line in lines:
            if current_y + height > max_bottom:
                break
            draw.text((text_start_x, current_y), line, font=font, fill=fill)
            current_y += height

    product_name = (product.name or "").upper()
    if show_name and product_name:
        name_lines = wrap_text(product_name, name_font)
        draw_wrapped_lines(name_lines, name_font, text_color, available_text_bottom)

    if show_description:
        if product.description:
            description_text = product.description.strip()
            description_fill = text_color
        else:
            description_text = "No description available"
            description_fill = (136, 136, 136)

        wrapped_description = wrap_text(description_text, description_font)
        draw_wrapped_lines(wrapped_description, description_font, description_fill, available_text_bottom)

    if show_sku and product.sku:
        sku_text = product.sku
        sku_height = line_height(sku_font)
        sku_y = max(current_y, text_bottom_limit - sku_height)
        draw.text((text_start_x, sku_y), sku_text, font=sku_font, fill=(85, 85, 85))

    response = HttpResponse(content_type="image/jpeg")
    filename = f"{product.sku or product.id}_qr.jpg"
    if "download" in request.GET:
        disposition = f"attachment; filename={filename}"
    else:
        disposition = f"inline; filename={filename}"
    response["Content-Disposition"] = disposition
    label_image.save(response, format="JPEG", dpi=(dpi, dpi), quality=95)
    return response


@login_required
def qr_stock_in(request, product_id):
    """Display a quick inventory transaction form for QR code scans."""

    product = get_object_or_404(
        Product,
        id=product_id,
        user__in=_get_inventory_stock_user_ids(request),
    )
    transaction_types = InventoryTransaction.TRANSACTION_TYPES

    if request.method == "POST":
        try:
            quantity = int(request.POST.get("quantity", 0))
        except (TypeError, ValueError):
            quantity = 0

        transaction_type = request.POST.get("transaction_type", "IN")
        if transaction_type not in dict(transaction_types).keys():
            transaction_type = "IN"

        remarks = request.POST.get("remarks", "").strip()
        if not remarks:
            remarks = "QR Transaction"

        if quantity > 0:
            InventoryTransaction.objects.create(
                product=product,
                transaction_type=transaction_type,
                quantity=quantity,
                transaction_date=timezone.now(),
                remarks=remarks,
                user=request.user,
            )
            messages.success(request, "Inventory updated successfully.")
            return redirect("accounts:inventory_transactions")
        else:
            messages.error(request, "Please enter a valid quantity.")

    context = {
        "product": product,
        "transaction_types": transaction_types,
    }
    return render(request, "inventory/qr_stock_in.html", context)


@login_required
def search_inventory(request):
    """Return basic JSON results for product search autocomplete."""
    query = request.GET.get("q", "").strip()
    results = []
    if query:
        product_user_ids = _get_inventory_user_ids(request)
        products = (
            Product.objects.filter(user__in=product_user_ids)
            .filter(
                Q(name__icontains=query)
                | Q(sku__icontains=query)
                | Q(description__icontains=query)
                | Q(category__name__icontains=query)
                | Q(supplier__name__icontains=query)
            )
            .select_related("category", "supplier")[:5]
        )

        for p in products:
            results.append(
                {
                    "id": p.id,
                    "label": f"{p.name} ({p.sku})",
                    "type": "product",
                }
            )

    return JsonResponse({"results": results})


@login_required
def filter_options(request):
    """Return products, suppliers, and categories based on current filter selections."""
    supplier_id = request.GET.get("supplier")
    category_id = request.GET.get("category")
    product_id = request.GET.get("product")

    product_user_ids = _get_inventory_user_ids(request)
    products = Product.objects.filter(user__in=product_user_ids)
    suppliers = Supplier.objects.filter(user__in=product_user_ids)
    categories = Category.objects.filter(user__in=product_user_ids)

    if supplier_id:
        products = products.filter(supplier_id=supplier_id)
        categories = categories.filter(products__supplier_id=supplier_id).distinct()

    if category_id:
        products = products.filter(category_id=category_id)
        suppliers = suppliers.filter(products__category_id=category_id).distinct()

    if product_id:
        try:
            product = Product.objects.get(id=product_id, user=user)
            if product.supplier_id:
                suppliers = suppliers.filter(id=product.supplier_id)
            else:
                suppliers = suppliers.none()
            if product.category_id:
                categories = categories.filter(id=product.category_id)
            else:
                categories = categories.none()
        except Product.DoesNotExist:
            products = products.none()
            suppliers = suppliers.none()
            categories = categories.none()

    data = {
        "products": [{"id": p.id, "name": p.name} for p in products.distinct()],
        "suppliers": [{"id": s.id, "name": s.name} for s in suppliers.distinct()],
        "categories": [{"id": c.id, "name": c.name} for c in categories.distinct()],
    }

    return JsonResponse(data)


@login_required
def inventory_analytics(request):
    stock_user_ids = _get_inventory_stock_user_ids(request)
    period_days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=period_days)

    products = Product.objects.filter(user__in=stock_user_ids)

    turnover_data = []
    for p in products:
        sold = p.transactions.filter(
            transaction_type='OUT',
            transaction_date__gte=start_date
        ).aggregate(total=Sum('quantity'))['total'] or 0
        avg_stock = (p.quantity_in_stock + sold) / 2 if sold else p.quantity_in_stock
        turnover = sold / avg_stock if avg_stock else 0
        turnover_data.append({'product': p, 'qty_sold': sold, 'turnover': round(turnover, 2)})

    top_sellers = sorted(turnover_data, key=lambda x: x['qty_sold'], reverse=True)[:5]
    slow_movers = sorted(turnover_data, key=lambda x: x['qty_sold'])[:5]

    value_expr_cost = ExpressionWrapper(F('quantity_in_stock') * F('cost_price'), output_field=DecimalField(max_digits=12, decimal_places=2))
    value_expr_sale = ExpressionWrapper(F('quantity_in_stock') * F('sale_price'), output_field=DecimalField(max_digits=12, decimal_places=2))

    totals = products.aggregate(
        total_cost=Sum(value_expr_cost),
        total_retail=Sum(value_expr_sale)
    )
    totals = {k: v or Decimal('0.00') for k, v in totals.items()}

    low_stock = products.filter(
        item_type='inventory',
        quantity_in_stock__lt=F('reorder_level'),
    )
    unsold_days = period_days * 6
    cutoff = timezone.now() - timedelta(days=unsold_days)
    unsold = (
        products.annotate(
            last_sale=Max(
                'transactions__transaction_date',
                filter=Q(transactions__transaction_type='OUT')
            )
        )
        .filter(Q(last_sale__lt=cutoff) | Q(last_sale__isnull=True))
    )

    context = {
        'turnover_data': turnover_data,
        'top_sellers': top_sellers,
        'slow_movers': slow_movers,
        'totals': totals,
        'period_days': period_days,
        'low_stock_products': low_stock,
        'unsold_products': unsold,
        'unsold_days': unsold_days,
    }

    return render(request, 'inventory/analytics_dashboard.html', context)
