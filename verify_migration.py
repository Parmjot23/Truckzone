#!/usr/bin/env python
"""
Quick verification that the mechanic fields migration is working.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
django.setup()

from django.db import connection

print("🔍 Checking if mechanic_status column exists...")

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'accounts_workorder'
        AND column_name = 'mechanic_status'
    """)

    if cursor.fetchone():
        print("✅ mechanic_status column exists - migration applied!")
        print("📱 Your mobile app should now work.")
    else:
        print("❌ mechanic_status column missing - run migration:")
        print("python manage.py migrate")
