# Deploying to PythonAnywhere (Python 3.10)

These notes summarize the minimal steps that were tested against PythonAnywhere's default **Python 3.10** system image.

## 1. Clone the project and create a virtualenv

```bash
cd ~
git clone <your-fork-url> transtex
cd transtex
python3.10 -m venv venv
source venv/bin/activate
```

## 2. Install dependencies

The `requirements.txt` file now contains only libraries that ship wheels for Python 3.10 on PythonAnywhere. We also provide
`requirements_local.txt` that simply extends those packages with optional tooling.

```bash
pip install --upgrade pip wheel
pip install -r requirements.txt  # production stack
# or
pip install -r requirements_local.txt  # + developer extras
```

If you plan to use MySQL on PythonAnywhere set `DATABASE_URL` to your MySQL connection string; if you use the built-in SQLite
for smaller installs, no additional configuration is required.

## 3. Configure environment variables

Create a `.env` file in the project root (or add the variables to PythonAnywhere's **Web → Environment Variables** section):

```
SECRET_KEY=<django-secret>
DJANGO_SETTINGS_MODULE=blank_template.settings
DEBUG=False
ALLOWED_HOSTS=<your-pythonanywhere-domain>
DATABASE_URL=mysql://<user>:<password>@<host>/<db>  # optional if you stay on SQLite
EMAIL_HOST_PASSWORD=<app-password>
STRIPE_SECRET_KEY=...
STRIPE_PUBLISHABLE_KEY=...
STRIPE_WEBHOOK_SECRET=...
OPENAI_API_KEY=...
```

## 4. Configure the WSGI file

Edit `/var/www/<username>_pythonanywhere_com_wsgi.py` and add:

```python
import os
import sys
from pathlib import Path

project_root = Path("/home/<username>/transtex")
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blank_template.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Then reload the web app from the PythonAnywhere dashboard.

## 5. Collect static files & run migrations

```bash
python manage.py collectstatic --noinput
python manage.py migrate --noinput
```

## 6. Optional: background tasks

If you need cron-style jobs (for recurring expenses) create a **Scheduled Task** on PythonAnywhere that runs:

```
/home/<username>/transtex/venv/bin/python /home/<username>/transtex/manage.py runcrons
```

This document should give you everything you need to get the Django site online on PythonAnywhere with Python 3.10.
