#!/usr/bin/env python
"""
Complete deployment script for Transtex mobile app fixes.
Run this on your live server to fix all mobile app issues.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n🔧 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd='.')
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print(f"❌ {description} - FAILED")
            print(f"Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ {description} - ERROR: {e}")
        return False

def main():
    print("🚀 Deploying Transtex Mobile App Fixes...")

    # Step 1: Check Django environment
    try:
        import django
        from django.conf import settings
        from django.core.management import execute_from_command_line

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
        django.setup()
        print("✅ Django environment loaded")
    except Exception as e:
        print(f"❌ Django setup failed: {e}")
        return False

    # Step 2: Create any missing migrations
    if not run_command("python manage.py makemigrations", "Creating migrations"):
        return False

    # Step 3: Apply all migrations
    if not run_command("python manage.py migrate", "Applying migrations"):
        return False

    # Step 4: Check migration status
    if not run_command("python manage.py showmigrations accounts", "Checking accounts migrations"):
        return False

    # Step 5: Collect static files (if needed)
    run_command("python manage.py collectstatic --noinput", "Collecting static files")

    # Step 6: Test the mobile API endpoints
    print("\n🧪 Testing mobile API endpoints...")

    from django.test import Client
    from django.contrib.auth.models import User

    client = Client()

    # Find a mechanic user
    try:
        mechanic_users = User.objects.filter(mechanic_portal__isnull=False)
        if mechanic_users.exists():
            test_user = mechanic_users.first()
            print(f"✅ Found mechanic user: {test_user.username}")

            # Test login
            from rest_framework.authtoken.models import Token
            try:
                token = Token.objects.get(user=test_user)
                headers = {'HTTP_AUTHORIZATION': f'Token {token.key}'}

                # Test summary endpoint
                response = client.get('/api/mechanic/summary/', **headers)
                if response.status_code == 200:
                    print("✅ Mechanic summary API working")
                else:
                    print(f"❌ Summary API error: {response.status_code}")
                    print(f"Response: {response.content.decode()}")

                # Test jobs endpoint
                response = client.get('/api/jobs/', **headers)
                if response.status_code == 200:
                    print("✅ Jobs API working")
                else:
                    print(f"❌ Jobs API error: {response.status_code}")
                    print(f"Response: {response.content.decode()}")

            except Token.DoesNotExist:
                print(f"⚠️  No token found for user {test_user.username}")

        else:
            print("⚠️  No mechanic users found. You'll need to create one via admin.")

    except Exception as e:
        print(f"❌ API test error: {e}")

    print("\n" + "="*50)
    print("🎉 DEPLOYMENT COMPLETE!")
    print("="*50)
    print("\n📱 Your mobile app should now work!")
    print("\nIf you still see errors:")
    print("1. Make sure you have a mechanic user with portal access")
    print("2. Try logging out and back in on the mobile app")
    print("3. Check that your web server has restarted")

    return True

if __name__ == '__main__':
    success = main()
    if success:
        print("\n✅ All fixes applied successfully!")
    else:
        print("\n❌ Deployment failed. Check the error messages above.")
        sys.exit(1)
