# accounts/templatetags/math_filters.py
from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def mul(value, arg):
    try:
        return Decimal(value) * Decimal(arg)
    except Exception:
        return ''
