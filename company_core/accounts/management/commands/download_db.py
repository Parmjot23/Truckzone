 # myapp/management/commands/download_db.py
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    def handle(self, *args, **options):
        shutil.copy(settings.DATABASES['default']['NAME'], 'database_backup.db')
        self.stdout.write(self.style.SUCCESS('Database backup created.'))