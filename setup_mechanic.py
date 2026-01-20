#!/usr/bin/env python
"""
Setup script to create mechanic user and link to portal account.
Run this on your live server at https://www.itranstech.ca
"""

import os
import django
from django.conf import settings

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
django.setup()

from django.contrib.auth.models import User
from accounts.models import Mechanic, WorkOrderAssignment

def setup_mechanic():
    print("Setting up mechanic for Transtex app...")

    # Check if user exists
    username = input("Enter the username/email for the mechanic account: ").strip()

    try:
        user = User.objects.get(username=username)
        print(f"Found user: {user.username}")
    except User.DoesNotExist:
        try:
            user = User.objects.get(email=username)
            print(f"Found user by email: {user.username}")
        except User.DoesNotExist:
            print(f"User '{username}' not found. Please create the user first.")
            return

    # Check if mechanic already exists
    mechanic = getattr(user, 'mechanic_portal', None)
    if mechanic:
        print(f"Mechanic already exists: {mechanic.name}")
        return

    # Create mechanic
    mechanic_name = input("Enter mechanic name: ").strip()
    if not mechanic_name:
        mechanic_name = user.username

    mechanic = Mechanic.objects.create(
        name=mechanic_name,
        portal_user=user
    )

    print(f"Created mechanic: {mechanic.name}")
    print(f"Linked to user: {user.username}")

    # Test the mechanic portal access
    test_mechanic = getattr(user, 'mechanic_portal', None)
    if test_mechanic:
        print("✓ Mechanic portal access working")
    else:
        print("✗ Mechanic portal access failed")

    print("\nSetup complete! The mechanic can now log in to the app.")

if __name__ == '__main__':
    setup_mechanic()
