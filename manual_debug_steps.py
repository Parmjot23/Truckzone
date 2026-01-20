#!/usr/bin/env python
"""
Manual debug steps for job start button issue.
Run this step by step to identify the problem.
"""

import os
import requests
import json

def step_by_step_debug():
    print("🔧 Manual Debug Steps for Job Start Button")
    print("=" * 50)

    # Set database URL
    os.environ['DATABASE_URL'] = "postgresql://neondb_owner:npg_zSe0YpPf6iUq@ep-mute-recipe-a8piosxf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require"

    base_url = "https://www.itranstech.ca/api"

    print("\n📋 STEP 1: Login Test")
    username = input("Enter your mechanic username: ").strip()
    password = input("Enter your mechanic password: ").strip()

    login_response = requests.post(f"{base_url}/auth/login/", json={
        "username": username,
        "password": password
    }, timeout=10)

    print(f"Login status: {login_response.status_code}")

    if login_response.status_code != 200:
        print("❌ LOGIN FAILED - Check your credentials")
        print(f"Response: {login_response.text}")
        return

    token = login_response.json().get('token')
    headers = {"Authorization": f"Token {token}"}
    print("✅ Login successful")

    print("\n📋 STEP 2: Get Jobs List")
    jobs_response = requests.get(f"{base_url}/jobs/", headers=headers, timeout=10)
    print(f"Jobs list status: {jobs_response.status_code}")

    if jobs_response.status_code != 200:
        print("❌ JOBS FETCH FAILED")
        print(f"Response: {jobs_response.text}")
        return

    jobs = jobs_response.json()
    print(f"✅ Found {len(jobs)} jobs")

    if not jobs:
        print("⚠️  NO JOBS AVAILABLE - Cannot test start functionality")
        return

    # Get first job
    job = jobs[0]
    job_id = job['id']
    print(f"🎯 Testing with job: {job.get('title', 'Unknown')} (ID: {job_id})")

    print("\n📋 STEP 3: Get Job Details")
    detail_response = requests.get(f"{base_url}/jobs/{job_id}/", headers=headers, timeout=10)
    print(f"Job detail status: {detail_response.status_code}")

    if detail_response.status_code != 200:
        print("❌ JOB DETAIL FETCH FAILED")
        print(f"Response: {detail_response.text}")
        return

    job_detail = detail_response.json()
    mechanic_status = job_detail.get('mechanic_status', 'not_started')
    print(f"✅ Job status: {mechanic_status}")

    print("\n📋 STEP 4: Test Job Start")
    start_payload = {"action": "start"}
    print(f"Sending: {json.dumps(start_payload, indent=2)}")

    start_response = requests.post(
        f"{base_url}/jobs/{job_id}/timer/",
        json=start_payload,
        headers=headers,
        timeout=10
    )

    print(f"Job start status: {start_response.status_code}")
    print(f"Response: {start_response.text}")

    if start_response.status_code == 200:
        result = start_response.json()
        new_status = result.get('mechanic_status', 'unknown')
        print(f"✅ Job start successful! New status: {new_status}")

        print("\n📋 STEP 5: Verify Status Change")
        verify_response = requests.get(f"{base_url}/jobs/{job_id}/", headers=headers, timeout=10)

        if verify_response.status_code == 200:
            updated_job = verify_response.json()
            verified_status = updated_job.get('mechanic_status', 'unknown')
            print(f"✅ Verified status: {verified_status}")

            if verified_status == 'in_progress':
                print("\n🎉 SUCCESS! Job start is working correctly!")
                print("The issue might be in the mobile app's UI or state management.")
            else:
                print(f"\n⚠️  Status mismatch: Expected 'in_progress', got '{verified_status}'")
        else:
            print("❌ Verification failed")

    else:
        print("\n❌ JOB START FAILED!")
        print("This is why the start button is not responding.")
        print("\nPossible causes:")
        print("1. Job is already started")
        print("2. Permission issue")
        print("3. Database constraint")
        print("4. Network issue")

        # Try to get more details
        if start_response.status_code == 403:
            print("🔍 403 Forbidden - Check if user is assigned to this job")
        elif start_response.status_code == 404:
            print("🔍 404 Not Found - Job might not exist")
        elif start_response.status_code == 500:
            print("🔍 500 Server Error - Check server logs")

if __name__ == '__main__':
    step_by_step_debug()
