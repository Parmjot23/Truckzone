#!/usr/bin/env python
"""
Run migrations on Neon PostgreSQL database.
"""

import os
import sys

def main():
    # Check if DATABASE_URL is set
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL environment variable not set!")
        return False

    print("🔗 Connecting to Neon database...")

    # Setup Django
    import django
    from django.conf import settings
    from django.core.management import execute_from_command_line

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
    django.setup()

    print("📦 Running migrations...")
    print(f"Database URL: {database_url[:30]}...")

    # Run migrations
    from django.core.management import call_command
    try:
        call_command('migrate', verbosity=2)
        print("\n✅ All migrations applied to Neon database!")
        print("🎉 Your mobile app should now work!")
        return True
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        return False

if __name__ == '__main__':
    success = main()
    if not success:
        sys.exit(1)
