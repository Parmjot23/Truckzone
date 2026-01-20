#!/usr/bin/env python
"""
One-click fix for Transtex mobile app issues.
Run this on your live server.
"""

import os
import subprocess
import sys

def main():
    print("🚀 Fixing Transtex Mobile App...")

    # Set environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')

    # Run migrations
    print("\n📦 Running migrations...")
    result = subprocess.run([sys.executable, 'manage.py', 'migrate'],
                          capture_output=True, text=True)

    if result.returncode == 0:
        print("✅ Migrations applied successfully")
        print(result.stdout)
    else:
        print("❌ Migration failed")
        print(result.stderr)
        return False

    # Check status
    print("\n🔍 Checking accounts migrations...")
    result = subprocess.run([sys.executable, 'manage.py', 'showmigrations', 'accounts'],
                          capture_output=True, text=True)
    print(result.stdout)

    # Collect static
    print("\n🔧 Collecting static files...")
    subprocess.run([sys.executable, 'manage.py', 'collectstatic', '--noinput'],
                 capture_output=True)

    print("\n🎉 Fix complete!")
    print("\n📱 Next steps:")
    print("1. Restart your web server")
    print("2. Test the mobile app")
    print("3. If still errors, check server logs")

    return True

if __name__ == '__main__':
    success = main()
    if not success:
        sys.exit(1)
