#!/usr/bin/env python
"""
Script to run database migrations on the live server.
Copy this to your live server and run it.
"""

import os
import subprocess
import sys

def run_migrations():
    print("🚀 Running database migrations on live server...")

    try:
        # Run makemigrations first (in case there are any pending model changes)
        print("\n1. Creating any pending migrations...")
        result = subprocess.run([
            'python', 'manage.py', 'makemigrations'
        ], capture_output=True, text=True, cwd='.')

        print("makemigrations output:")
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)

        # Run migrate to apply all migrations
        print("\n2. Applying migrations...")
        result = subprocess.run([
            'python', 'manage.py', 'migrate'
        ], capture_output=True, text=True, cwd='.')

        print("migrate output:")
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)

        # Check migration status
        print("\n3. Checking migration status...")
        result = subprocess.run([
            'python', 'manage.py', 'showmigrations', 'accounts'
        ], capture_output=True, text=True, cwd='.')

        print("Migration status:")
        print(result.stdout)

        print("\n✅ Migrations completed!")
        print("The mechanic_status field should now be available.")

    except Exception as e:
        print(f"❌ Error running migrations: {e}")
        return False

    return True

if __name__ == '__main__':
    success = run_migrations()
    if success:
        print("\n🎉 Try the mobile app again - the 500 errors should be fixed!")
    else:
        print("\n❌ Migration failed. Please check the error messages above.")
