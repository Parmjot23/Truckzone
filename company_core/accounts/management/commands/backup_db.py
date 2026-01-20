import os
import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from blank.utils import get_db_config  # Adjust the import based on where get_db_config is defined

class Command(BaseCommand):
    help = 'Backup SQLite database'

    def handle(self, *args, **kwargs):
        # Use the get_db_config function to get the database configuration
        db_config = get_db_config('DATABASE_URL')
        db_path = db_config['NAME']
        backup_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'backups')  # Adjusted path to be consistent

        # Ensure the backup directory exists
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        backup_path = os.path.join(backup_dir, f'db_backup_{datetime.datetime.now().strftime("%Y-%m-%d")}.sqlite3')
        
        self.stdout.write(f'Attempting to backup database from {db_path} to {backup_path}...')

        if os.path.exists(db_path):
            self.stdout.write(f'Backing up database to {backup_path}...')
            with open(db_path, 'rb') as db_file:
                with open(backup_path, 'wb') as backup_file:
                    backup_file.write(db_file.read())
            self.stdout.write(self.style.SUCCESS(f'Successfully backed up database to {backup_path}'))
        else:
            self.stdout.write(self.style.ERROR(f'Database file not found at {db_path}'))
