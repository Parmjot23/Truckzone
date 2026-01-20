#!/usr/bin/env python3
"""
Development server startup script for Smart Invoices
"""
import os
import sys
import django
from django.core.management import execute_from_command_line

def main():
    """Start the Django development server"""
    # Set up Django environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
    
    # Add the project directory to Python path
    project_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_dir)
    
    # Initialize Django
    django.setup()

    # Ensure database schema is up to date before starting.
    # The --run-syncdb flag forces Django to create any missing tables or
    # columns even if migrations think they've already been applied. This
    # guards against environments where the migration for mechanic fields
    # was marked as done but the columns were never created.
    execute_from_command_line(['manage.py', 'migrate', '--run-syncdb'])

    # Start the development server
    print("🚀 Starting Smart Invoices development server...")
    print("📍 Server will be available at: http://127.0.0.1:8000")
    print("🛑 Press Ctrl+C to stop the server")
    print("-" * 50)

    # Run the development server
    execute_from_command_line(['manage.py', 'runserver', '127.0.0.1:8000'])

if __name__ == '__main__':
    main()
