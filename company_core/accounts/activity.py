"""Thread-local helpers for auditing business admin actions."""
from __future__ import annotations

import threading
from typing import Optional

from django.contrib.auth.models import AbstractBaseUser


_actor_storage = threading.local()


def set_current_actor(user: Optional[AbstractBaseUser]) -> None:
    """Store the acting user in thread-local storage for the current request."""
    if user is None:
        clear_current_actor()
        return
    _actor_storage.user = user


def get_current_actor() -> Optional[AbstractBaseUser]:
    """Return the user captured for the current thread if available."""
    return getattr(_actor_storage, "user", None)


def clear_current_actor() -> None:
    """Remove any stored actor from the thread-local context."""
    if hasattr(_actor_storage, "user"):
        delattr(_actor_storage, "user")
