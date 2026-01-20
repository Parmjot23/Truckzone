# accounts/templatetags/custom_filters.py

from django import template

register = template.Library()

@register.filter
def split(value, key):
    """Splits a string by the given key."""
    return value.split(key)

@register.filter
def currency(value):
    """Formats a number as currency."""
    try:
        return "${:,.2f}".format(float(value))
    except (ValueError, TypeError):
        return "$0.00"


@register.filter
def seconds_to_hms(total_seconds):
    """Convert a number of seconds to H:MM:SS for display."""
    try:
        seconds = int(total_seconds or 0)
    except (ValueError, TypeError):
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@register.filter
def iso_to_display(value):
    """
    Convert an ISO 8601 datetime string to 'Sept. 3, 2025, 3:55 p.m.' format.
    Returns the original value if parsing fails.
    """
    if not value:
        return ""
    try:
        from datetime import datetime
        from django.utils import timezone, formats

        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = timezone.localtime(dt)
        return formats.date_format(dt, "N j, Y, P")
    except Exception:
        return value


@register.filter
def underscore_to_space(value):
    """Replace underscores with spaces for more readable labels."""
    if value is None:
        return ""
    return str(value).replace("_", " ")
