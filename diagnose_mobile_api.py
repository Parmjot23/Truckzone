#!/usr/bin/env python
"""
Diagnostic script to test mobile API endpoints and find the exact error.
Run this on your live server to debug the 500 errors.
"""

import requests
import json
import sys

def test_mobile_endpoints():
    print("🔍 Diagnosing mobile API endpoints...")

    base_url = "https://www.itranstech.ca/api"

    # Get credentials
    username = input("Enter mechanic username: ").strip()
    password = input("Enter mechanic password: ").strip()

    # Test login
    print("\n1. Testing login...")
    login_url = f"{base_url}/auth/login/"
    login_data = {"username": username, "password": password}

    response = requests.post(login_url, json=login_data)

    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code}")
        print(f"Response: {response.text}")
        return

    data = response.json()
    token = data.get('token')

    if not token:
        print("❌ No token received")
        return

    print("✅ Login successful")

    headers = {"Authorization": f"Token {token}"}

    # Test summary endpoint
    print("\n2. Testing mechanic summary...")
    summary_url = f"{base_url}/mechanic/summary/"
    response = requests.get(summary_url, headers=headers)

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("✅ Summary API working!")
        print(f"Stats: {data.get('stats', {})}")
        print(f"Recent jobs: {len(data.get('recent', []))}")
    elif response.status_code == 403:
        print("❌ User is not a mechanic (need to link to Mechanic record)")
        print(f"Response: {response.text}")
    else:
        print(f"❌ Summary API failed: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 500:
            print("🔴 This is the 500 error we need to fix!")

    # Test jobs endpoint
    print("\n3. Testing jobs list...")
    jobs_url = f"{base_url}/jobs/"
    response = requests.get(jobs_url, headers=headers)

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("✅ Jobs API working!")
        print(f"Number of jobs: {len(data)}")
    elif response.status_code == 403:
        print("❌ User is not a mechanic")
        print(f"Response: {response.text}")
    else:
        print(f"❌ Jobs API failed: {response.status_code}")
        print(f"Response: {response.text}")

    # Test if there are any WorkOrderAssignments for this mechanic
    print("\n4. Checking WorkOrderAssignment records...")
    try:
        from django.conf import settings
        import os
        import django

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
        django.setup()

        from accounts.models import Mechanic, WorkOrderAssignment
        from django.contrib.auth.models import User

        user = User.objects.filter(username=username).first()
        if user:
            mechanic = getattr(user, 'mechanic_portal', None)
            if mechanic:
                assignments_count = WorkOrderAssignment.objects.filter(mechanic=mechanic).count()
                print(f"✅ Found {assignments_count} work order assignments for this mechanic")

                if assignments_count == 0:
                    print("⚠️  No work order assignments found - this might be why jobs list is empty")
            else:
                print("❌ No mechanic record found for this user")
        else:
            print("❌ User not found in database")

    except Exception as e:
        print(f"❌ Error checking database: {e}")

if __name__ == '__main__':
    test_mobile_endpoints()
