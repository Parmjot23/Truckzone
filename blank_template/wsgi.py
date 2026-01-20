"""
WSGI config for blank_template project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/howto/deployment/wsgi/
"""

import logging
import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from whitenoise import WhiteNoise

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')

logger = logging.getLogger(__name__)

# Log whether Google Maps browser key is available. This helps diagnose
# "Autocomplete/route not working" issues on platforms like Koyeb where missing
# env vars are a common root cause. We only log presence + length (never the key).
try:
    _maps_key = (getattr(settings, "GOOGLE_MAPS_API_KEY", "") or "").strip()
    logger.info("GOOGLE_MAPS_API_KEY configured=%s len=%s", bool(_maps_key), len(_maps_key))
except Exception:
    # Never block startup if logging fails
    pass

django_application = get_wsgi_application()

# Wrap the default Django WSGI application with WhiteNoise so static assets are
# always served by the process itself (e.g., when running on platforms like
# Koyeb where there is no separate static file server). WhiteNoise gracefully
# skips directories that do not yet exist, which keeps first boot deployments
# from crashing even if collectstatic has not completed.
application = WhiteNoise(django_application)

static_root = getattr(settings, 'STATIC_ROOT', None)
if static_root:
    application.add_files(static_root, prefix='static/')

for extra_dir in getattr(settings, 'STATICFILES_DIRS', []):
    application.add_files(extra_dir, prefix='static/')
