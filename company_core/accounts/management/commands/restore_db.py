import os
import shutil
import datetime
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Restore SQLite database from a backup'

    def add_arguments(self, parser):
        parser.add_argument('backup_file', type=str, help='The backup file to restore from')

    def handle(self, *args, **kwargs):
        backup_file = kwargs['backup_file']
        db_dir = '/home/app/db_backups'  # Change this to a writable directory
        db_path = os.path.join(db_dir, 'database.db')

        if not os.path.exists(backup_file):
            self.stdout.write(self.style.ERROR(f'Backup file not found: {backup_file}'))
            return

        # Ensure the directory for the database exists
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            self.stdout.write(self.style.WARNING(f'Directory {db_dir} created.'))

        self.stdout.write(f'Restoring database from {backup_file} to {db_path}...')

        # Backup current database if it exists
        if os.path.exists(db_path):
            current_backup_path = f'{db_dir}/database_backup_{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.sqlite3'
            shutil.copy2(db_path, current_backup_path)
            self.stdout.write(self.style.SUCCESS(f'Current database backed up to {current_backup_path}'))

        # Restore the backup
        shutil.copy2(backup_file, db_path)
        self.stdout.write(self.style.SUCCESS(f'Successfully restored database from {backup_file} to {db_path}'))
