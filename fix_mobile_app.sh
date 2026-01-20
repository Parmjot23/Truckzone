#!/bin/bash

echo "🚀 Fixing Transtex Mobile App Issues..."

# Set Django environment
export DJANGO_SETTINGS_MODULE=blank_template.settings

echo "📦 Applying database migrations..."
python manage.py migrate

echo "🔍 Checking migration status..."
python manage.py showmigrations accounts

echo "🔧 Collecting static files..."
python manage.py collectstatic --noinput

echo "🧪 Testing mobile API..."
python -c "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
django.setup()

from django.contrib.auth.models import User
from django.test import Client

client = Client()
mechanic_users = User.objects.filter(mechanic_portal__isnull=False)

if mechanic_users.exists():
    user = mechanic_users.first()
    from rest_framework.authtoken.models import Token
    try:
        token = Token.objects.get(user=user)
        headers = {'HTTP_AUTHORIZATION': f'Token {token.key}'}

        # Test summary
        response = client.get('/api/mechanic/summary/', **headers)
        print(f'Summary API: {response.status_code}')

        # Test jobs
        response = client.get('/api/jobs/', **headers)
        print(f'Jobs API: {response.status_code}')

        if response.status_code == 200:
            print('✅ Mobile APIs working!')
        else:
            print('❌ APIs still failing - check server logs')
    except:
        print('⚠️  No token found - login to create one')
else:
    print('⚠️  No mechanic users found')
"

echo ""
echo "🎉 Fix complete! Restart your web server and test the mobile app."
echo ""
echo "If you still see errors:"
echo "1. Restart your web server (nginx/gunicorn/etc)"
echo "2. Make sure mechanic users exist in admin"
echo "3. Clear mobile app cache and relogin"
