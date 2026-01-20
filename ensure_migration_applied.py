#!/usr/bin/env python
"""
Script to ensure the mechanic fields migration is properly applied.
Run this on your live server after running 'python manage.py migrate'.
"""

import os
import django
from django.conf import settings
from django.db import connection

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
django.setup()

def check_migration_status():
    """Check if the critical migrations have been applied."""
    print("🔍 Checking migration status...")

    required_migrations = [
        "0002_groupedestimate_tax_exempt_and_more",
        "0042_vehicle_license_plate",
    ]

    missing = []

    with connection.cursor() as cursor:
        # Check django_migrations table
        cursor.execute(
            """
            SELECT name, applied
            FROM django_migrations
            WHERE app = 'accounts' AND name IN %s
            """,
            [tuple(required_migrations)],
        )

        applied = {row[0] for row in cursor.fetchall()}
        for migration in required_migrations:
            if migration in applied:
                print(f"✅ Migration {migration} is applied")
            else:
                missing.append(migration)
                print(f"❌ Migration {migration} is NOT applied")

    return not missing

def check_mechanic_columns():
    """Check if all mechanic columns exist."""
    print("\n🔍 Checking WorkOrder table columns...")

    mechanic_columns = [
        'mechanic_status',
        'mechanic_started_at',
        'mechanic_ended_at',
        'mechanic_paused_at',
        'mechanic_total_paused_seconds',
        'mechanic_pause_reason',
        'mechanic_pause_log',
        'mechanic_travel_started_at',
        'mechanic_total_travel_seconds',
        'mechanic_marked_complete',
        'mechanic_completed_at',
        'signature_file',
        'media_files',
        'completed_at'
    ]

    missing_columns = []

    with connection.cursor() as cursor:
        for column in mechanic_columns:
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'accounts_workorder'
                AND column_name = %s
            """, [column])

            if not cursor.fetchone():
                missing_columns.append(column)

    if missing_columns:
        print(f"❌ Missing columns: {', '.join(missing_columns)}")
        return False
    else:
        print("✅ All mechanic columns are present")
        return True


def check_vehicle_columns():
    """Check if the vehicle table has the expected columns."""
    print("\n🔍 Checking Vehicle table columns (accounts_vehicle)...")

    expected_columns = [
        "license_plate",
    ]

    missing_columns = []

    with connection.cursor() as cursor:
        for column in expected_columns:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'accounts_vehicle'
                AND column_name = %s
                """,
                [column],
            )

            if not cursor.fetchone():
                missing_columns.append(column)

    if missing_columns:
        print(f"❌ Missing vehicle columns: {', '.join(missing_columns)}")
        print(
            "   ➤ Run `python manage.py migrate accounts 0042` to add the missing "
            "license_plate column."
        )
        return False

    print("✅ Vehicle columns are present")
    return True

def test_api_endpoints():
    """Test the mobile API endpoints."""
    print("\n🧪 Testing mobile API endpoints...")

    from django.contrib.auth.models import User
    from django.test import Client

    client = Client()

    # Find mechanic users
    mechanic_users = User.objects.filter(mechanic_portal__isnull=False)

    if not mechanic_users.exists():
        print("⚠️  No mechanic users found. Create one in Django admin first.")
        return False

    user = mechanic_users.first()
    print(f"✅ Testing with mechanic user: {user.username}")

    # Get or create token
    from rest_framework.authtoken.models import Token

    token, created = Token.objects.get_or_create(user=user)
    if created:
        print("✅ Created new token for user")

    headers = {'HTTP_AUTHORIZATION': f'Token {token.key}'}

    # Test summary endpoint
    response = client.get('/api/mechanic/summary/', **headers)
    if response.status_code == 200:
        print("✅ Mechanic summary API working")
        return True
    else:
        print(f"❌ Summary API failed: {response.status_code}")
        print(f"Response: {response.content.decode()}")
        return False

def main():
    print("🚀 Ensuring Transtex mobile migration is applied...")

    # Check migration status
    migration_applied = check_migration_status()

    if not migration_applied:
        print("\n❌ Migration not applied. Run this command on your live server:")
        print("python manage.py migrate")
        return False

    # Check columns
    columns_ok = check_mechanic_columns() and check_vehicle_columns()

    if not columns_ok:
        print("\n❌ Some columns are missing. Try running migration again:")
        print("python manage.py migrate --run-syncdb")
        return False

    # Test API
    api_ok = test_api_endpoints()

    if api_ok:
        print("\n🎉 Everything is working! Your mobile app should now work.")
        return True
    else:
        print("\n❌ API test failed. Check the error messages above.")
        return False

if __name__ == '__main__':
    success = main()
    if success:
        print("\n✅ Mobile app is ready!")
    else:
        print("\n❌ Issues found. Fix them and try again.")
