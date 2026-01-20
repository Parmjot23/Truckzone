"""Utility helpers for PDF rendering and caching."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.template.loader import render_to_string
from django.utils import timezone
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    HTML = None

DEFAULT_CACHE_SUBDIR = "invoices/generated"


def apply_branding_defaults(context: dict) -> dict:
    """
    Ensure branding keys exist even when templates are rendered without a RequestContext.

    Prefer DB-backed values (profile/company) and fall back to settings defaults.
    """
    if context is None:
        return {}

    default_business_name = (
        getattr(settings, "DEFAULT_BUSINESS_NAME", "Truck Zone")
        or "Truck Zone"
    )
    context.setdefault("default_business_name", default_business_name)

    profile = context.get("profile") or context.get("business_profile")
    business_info = context.get("business_info")
    business_user = context.get("business_user") or context.get("owner")

    request = context.get("request")
    request_user = getattr(request, "user", None) if request is not None else None
    user = context.get("user") or request_user

    if profile is None and business_user is not None:
        profile = getattr(business_user, "profile", None)
    if profile is None and user is not None:
        profile = getattr(user, "profile", None)

    business_name = None
    if profile is not None:
        business_name = getattr(profile, "company_name", None)
    if not business_name and business_info is not None:
        if isinstance(business_info, dict):
            business_name = business_info.get("name")
        else:
            business_name = getattr(business_info, "name", None)
    if not business_name:
        business_name = context.get("business_name")
    if not business_name and business_user is not None:
        business_name = business_user.get_full_name() or business_user.get_username()
    if not business_name and user is not None:
        business_name = user.get_full_name() or user.get_username()

    context["business_name"] = business_name or default_business_name
    return context


def _storage_is_cloudinary() -> bool:
    """
    True when the default storage backend is Cloudinary.

    We avoid caching PDFs into Cloudinary because it is unnecessary and consumes resources.
    PDFs should be generated on-demand for email/print/download.
    """
    if getattr(settings, "USE_CLOUDINARY_STORAGE", False):
        return True
    storage_cls = getattr(default_storage, "__class__", None)
    storage_mod = (getattr(storage_cls, "__module__", "") or "").lower()
    storage_name = (getattr(storage_cls, "__name__", "") or "").lower()
    return ("cloudinary" in storage_mod) or ("cloudinary" in storage_name)


def _pdf_cache_enabled() -> bool:
    """
    Allow disabling invoice PDF caching.

    Default: enabled, but automatically disabled when Cloudinary is active.
    """
    enabled = getattr(settings, "INVOICE_PDF_CACHE_ENABLED", True)
    return bool(enabled) and not _storage_is_cloudinary()


def _cache_directory() -> str:
    configured = getattr(settings, "INVOICE_PDF_CACHE_SUBDIR", DEFAULT_CACHE_SUBDIR)
    # Normalise to a simple forward-slash path for the configured storage backend
    return str(Path(configured).as_posix())


def _object_timestamp(obj) -> datetime:
    timestamp = getattr(obj, "updated_at", None) or getattr(obj, "created_at", None)
    if timestamp is None:
        timestamp = timezone.now()
    return timestamp


def _purge_old_cached_files(directory: str, prefix: str) -> None:
    try:
        _, files = default_storage.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return

    for name in files:
        if name.startswith(prefix):
            default_storage.delete(f"{directory}/{name}")


def render_html_to_pdf(html: str, *, stylesheets: Iterable = (), base_url: str | None = None) -> bytes:
    """Render an HTML string to PDF bytes."""
    if not WEASYPRINT_AVAILABLE:
        raise ImportError("WeasyPrint is not available. PDF generation is disabled. Please install GTK+ libraries for Windows or use a different PDF generation method.")
    buffer = BytesIO()
    HTML(string=html, base_url=base_url).write_pdf(target=buffer, stylesheets=list(stylesheets))
    return buffer.getvalue()


def render_template_to_pdf(
    template: str,
    context: dict,
    *,
    stylesheets: Iterable = (),
    base_url: str | None = None,
) -> bytes:
    context = apply_branding_defaults(context)
    html = render_to_string(template, context)
    return render_html_to_pdf(html, stylesheets=stylesheets, base_url=base_url)


def render_template_to_pdf_cached(
    obj,
    template: str,
    context: dict,
    *,
    cache_prefix: str,
    stylesheets: Iterable = (),
) -> bytes:
    """Render a template to PDF bytes with simple storage-backed caching."""
    context = apply_branding_defaults(context)
    # Never store invoice PDFs in Cloudinary (resource-heavy and unnecessary).
    if not _pdf_cache_enabled():
        return render_template_to_pdf(template, context, stylesheets=stylesheets)

    object_pk = getattr(obj, 'pk', None)
    if object_pk is None:
        return render_template_to_pdf(template, context, stylesheets=stylesheets)

    directory = _cache_directory()
    timestamp = _object_timestamp(obj)
    filename = f"{cache_prefix}_{object_pk}_{timestamp.strftime('%Y%m%d%H%M%S')}".strip()
    cache_path = f"{directory}/{filename}.pdf"

    if default_storage.exists(cache_path):
        with default_storage.open(cache_path, "rb") as cached_file:
            return cached_file.read()

    # Remove older cached variants for the same object to avoid orphaned files
    _purge_old_cached_files(directory, f"{cache_prefix}_{object_pk}_")

    pdf_bytes = render_template_to_pdf(template, context, stylesheets=stylesheets)
    default_storage.save(cache_path, ContentFile(pdf_bytes))
    return pdf_bytes
