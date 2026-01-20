# templatetags/custom_tags.py
from django import template

register = template.Library()

@register.filter
def index(List, i):
    try:
        return List[int(i)]
    except:
        return None

@register.filter
def get_item(value, key):
    """Return an item from ``value`` using ``key``.

    Supports dictionary, list, and tuple lookups and gracefully returns
    ``None`` when the lookup fails. This is useful inside templates where the
    default ``[]`` syntax is not available.
    """

    if value is None:
        return None

    # Try direct lookup (works for dicts with matching key types as well as
    # lists/tuples when ``key`` is already an integer).
    try:
        return value[key]
    except (TypeError, KeyError, IndexError):
        pass

    # Fall back to string representation (covers dicts keyed by strings when a
    # non-string ``key`` is provided).
    try:
        return value[str(key)]
    except (TypeError, KeyError, IndexError):
        pass

    # Finally, attempt integer conversion for list/tuple indexes provided as
    # strings.
    try:
        index = int(key)
    except (TypeError, ValueError):
        return None

    try:
        return value[index]
    except (TypeError, KeyError, IndexError):
        return None
