#!/usr/bin/env python
"""
Debug script to test job start functionality.
This will help identify why the start job button is not working.
"""

import os
import requests
import json

def test_job_start():
    print("🔍 Debugging job start functionality...")

    # Set the Neon database URL
    os.environ['DATABASE_URL'] = "postgresql://neondb_owner:npg_zSe0YpPf6iUq@ep-mute-recipe-a8piosxf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require"

    # Get credentials
    username = input("Enter mechanic username: ").strip()
    password = input("Enter mechanic password: ").strip()

    base_url = "https://www.itranstech.ca/api"

    # Step 1: Login
    print("\n1. Logging in...")
    login_response = requests.post(f"{base_url}/auth/login/", json={
        "username": username,
        "password": password
    }, timeout=10)

    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        print(f"Response: {login_response.text}")
        return

    token = login_response.json().get('token')
    headers = {"Authorization": f"Token {token}"}
    print("✅ Login successful")

    # Step 2: Get jobs list
    print("\n2. Fetching jobs list...")
    jobs_response = requests.get(f"{base_url}/jobs/", headers=headers, timeout=10)

    if jobs_response.status_code != 200:
        print(f"❌ Jobs fetch failed: {jobs_response.status_code}")
        print(f"Response: {jobs_response.text}")
        return

    jobs = jobs_response.json()
    print(f"✅ Found {len(jobs)} jobs")

    if not jobs:
        print("⚠️  No jobs available to test")
        return

    # Step 3: Pick first job
    job = jobs[0]
    job_id = job.get('id')
    print(f"🎯 Testing with job ID: {job_id}")
    print(f"Job title: {job.get('title', 'Unknown')}")

    # Step 4: Get job details
    print("\n3. Fetching job details...")
    detail_response = requests.get(f"{base_url}/jobs/{job_id}/", headers=headers, timeout=10)

    if detail_response.status_code != 200:
        print(f"❌ Job detail fetch failed: {detail_response.status_code}")
        print(f"Response: {detail_response.text}")
        return

    job_detail = detail_response.json()
    current_status = job_detail.get('mechanic_status', 'unknown')
    print(f"✅ Job current status: {current_status}")

    # Step 5: Test job start
    print("\n4. Testing job start...")
    start_payload = {"action": "start"}
    start_response = requests.post(
        f"{base_url}/jobs/{job_id}/timer/",
        json=start_payload,
        headers=headers,
        timeout=10
    )

    print(f"Start request status: {start_response.status_code}")
    print(f"Start request response: {start_response.text}")

    if start_response.status_code == 200:
        result = start_response.json()
        print("✅ Job start successful!")
        print(f"New status: {result.get('mechanic_status', 'unknown')}")

        # Verify the change
        print("\n5. Verifying job status change...")
        verify_response = requests.get(f"{base_url}/jobs/{job_id}/", headers=headers, timeout=10)

        if verify_response.status_code == 200:
            updated_job = verify_response.json()
            updated_status = updated_job.get('mechanic_status', 'unknown')
            print(f"✅ Verified new status: {updated_status}")

            if updated_status == 'in_progress':
                print("🎉 Job start is working correctly!")
            else:
                print(f"⚠️  Status not updated as expected. Expected 'in_progress', got '{updated_status}'")
        else:
            print(f"❌ Verification failed: {verify_response.status_code}")

    else:
        print("❌ Job start failed!")
        print("This is why the start button is not responding.")
        print("Possible causes:")
        print("1. Job is already started")
        print("2. User doesn't have permission")
        print("3. Database error")
        print("4. Network connectivity issue")

if __name__ == '__main__':
    test_job_start()
