#!/usr/bin/env python
"""
Script to check and verify the database schema on live server.
This will help diagnose if the mechanic_status column exists.
"""

import os
import django
from django.conf import settings
from django.db import connection

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
django.setup()

def check_workorder_columns():
    print("🔍 Checking WorkOrder table schema...")

    with connection.cursor() as cursor:
        try:
            # Check if mechanic_status column exists
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'accounts_workorder'
                AND column_name = 'mechanic_status'
            """)

            result = cursor.fetchone()

            if result:
                print("✅ mechanic_status column exists!")
            else:
                print("❌ mechanic_status column is missing!")
                return False

            # Check other mechanic fields
            mechanic_fields = [
                'mechanic_started_at',
                'mechanic_ended_at',
                'mechanic_paused_at',
                'mechanic_total_paused_seconds',
                'mechanic_total_travel_seconds',
                'mechanic_pause_log',
                'mechanic_pause_reason',
                'mechanic_marked_complete',
                'mechanic_completed_at',
                'media_files',
                'signature_file',
                'completed_at'
            ]

            print("\nChecking other mechanic fields:")
            missing_fields = []

            for field in mechanic_fields:
                cursor.execute(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'accounts_workorder'
                    AND column_name = '{field}'
                """)

                if not cursor.fetchone():
                    missing_fields.append(field)
                    print(f"❌ {field} - MISSING")
                else:
                    print(f"✅ {field} - OK")

            if missing_fields:
                print(f"\n❌ Missing fields: {', '.join(missing_fields)}")
                return False
            else:
                print("\n✅ All mechanic fields are present!")
                return True

        except Exception as e:
            print(f"❌ Database error: {e}")
            return False

def test_mechanic_api():
    print("\n🧪 Testing mechanic API endpoints...")

    import requests

    # Get credentials
    username = input("Enter mechanic username: ").strip()
    password = input("Enter mechanic password: ").strip()

    # Test login
    try:
        response = requests.post('https://www.itranstech.ca/api/auth/login/', json={
            "username": username,
            "password": password
        }, timeout=10)

        if response.status_code != 200:
            print(f"❌ Login failed: {response.status_code}")
            return

        token = response.json().get('token')
        headers = {"Authorization": f"Token {token}"}

        # Test summary
        response = requests.get('https://www.itranstech.ca/api/mechanic/summary/', headers=headers, timeout=10)
        if response.status_code == 200:
            print("✅ Mechanic summary API working!")
        else:
            print(f"❌ Summary API error: {response.status_code}")
            print(f"Response: {response.text}")

        # Test jobs
        response = requests.get('https://www.itranstech.ca/api/jobs/', headers=headers, timeout=10)
        if response.status_code == 200:
            jobs = response.json()
            print(f"✅ Jobs API working! Found {len(jobs)} jobs")
        else:
            print(f"❌ Jobs API error: {response.status_code}")
            print(f"Response: {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")

if __name__ == '__main__':
    schema_ok = check_workorder_columns()
    if schema_ok:
        print("\n🎉 Database schema looks good!")
        test_mechanic_api()
    else:
        print("\n❌ Database schema issues found. Run migrations!")
