#!/usr/bin/env python
"""
Quick verification script for mobile API fixes.
Run this after deploying the changes to test if the 500 errors are resolved.
"""

import requests
import json

def quick_test():
    print("🚀 Quick test of mobile API endpoints...")

    base_url = "https://www.itranstech.ca/api"

    # Get credentials
    username = input("Enter mechanic username: ").strip()
    password = input("Enter mechanic password: ").strip()

    # Test login
    login_response = requests.post(f"{base_url}/auth/login/", json={
        "username": username,
        "password": password
    })

    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        return

    token = login_response.json().get('token')
    headers = {"Authorization": f"Token {token}"}

    # Test summary (was returning 500)
    summary_response = requests.get(f"{base_url}/mechanic/summary/", headers=headers)
    print(f"Summary endpoint: {summary_response.status_code}")

    if summary_response.status_code == 200:
        print("✅ Summary working!")
    elif summary_response.status_code == 500:
        print("❌ Still 500 error in summary")
        print(f"Response: {summary_response.text}")
    else:
        print(f"Other status: {summary_response.status_code}")
        print(f"Response: {summary_response.text}")

    # Test jobs list (was returning 500)
    jobs_response = requests.get(f"{base_url}/jobs/", headers=headers)
    print(f"Jobs endpoint: {jobs_response.status_code}")

    if jobs_response.status_code == 200:
        jobs = jobs_response.json()
        print(f"✅ Jobs working! Found {len(jobs)} jobs")
    elif jobs_response.status_code == 500:
        print("❌ Still 500 error in jobs")
        print(f"Response: {jobs_response.text}")
    else:
        print(f"Other status: {jobs_response.status_code}")
        print(f"Response: {jobs_response.text}")

if __name__ == '__main__':
    quick_test()
