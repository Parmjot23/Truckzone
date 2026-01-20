#!/usr/bin/env python
"""
Force fix Neon database schema by manually creating missing columns.
"""

import os
import sys

def fix_neon_schema():
    # Set the Neon database URL
    os.environ['DATABASE_URL'] = "postgresql://neondb_owner:npg_zSe0YpPf6iUq@ep-mute-recipe-a8piosxf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require"

    print("🔧 Fixing Neon database schema...")

    # Setup Django
    import django
    from django.conf import settings
    from django.core.management import execute_from_command_line

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blank_template.settings')
    django.setup()

    # Test database connection
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            print("📋 Checking WorkOrder table schema...")

            # Check if mechanic_status column exists
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'accounts_workorder'
                AND column_name = 'mechanic_status'
            """)

            if cursor.fetchone():
                print("✅ mechanic_status column already exists!")
                return True

            print("❌ mechanic_status column missing - creating it...")

            # Add the missing columns manually
            mechanic_columns = [
                ("mechanic_status", "VARCHAR(16) DEFAULT 'not_started'"),
                ("mechanic_started_at", "TIMESTAMP WITH TIME ZONE NULL"),
                ("mechanic_ended_at", "TIMESTAMP WITH TIME ZONE NULL"),
                ("mechanic_paused_at", "TIMESTAMP WITH TIME ZONE NULL"),
                ("mechanic_total_paused_seconds", "INTEGER DEFAULT 0"),
                ("mechanic_pause_reason", "TEXT NULL"),
                ("mechanic_pause_log", "JSONB DEFAULT '[]'::jsonb"),
                ("mechanic_travel_started_at", "TIMESTAMP WITH TIME ZONE NULL"),
                ("mechanic_total_travel_seconds", "INTEGER DEFAULT 0"),
                ("mechanic_marked_complete", "BOOLEAN DEFAULT FALSE"),
                ("mechanic_completed_at", "TIMESTAMP WITH TIME ZONE NULL"),
                ("signature_file", "VARCHAR(100) NULL"),
                ("media_files", "JSONB DEFAULT '[]'::jsonb"),
                ("completed_at", "TIMESTAMP WITH TIME ZONE NULL"),
            ]

            for column_name, column_def in mechanic_columns:
                try:
                    # Check if column exists first
                    cursor.execute(f"""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'accounts_workorder'
                        AND column_name = '{column_name}'
                    """)

                    if not cursor.fetchone():
                        # Add the column
                        cursor.execute(f"""
                            ALTER TABLE accounts_workorder
                            ADD COLUMN {column_name} {column_def}
                        """)
                        print(f"✅ Added column: {column_name}")
                    else:
                        print(f"ℹ️  Column already exists: {column_name}")

                except Exception as e:
                    print(f"❌ Error adding column {column_name}: {e}")

            print("\n🔍 Verifying all columns were added...")

            # Verify all columns exist
            missing_columns = []
            for column_name, _ in mechanic_columns:
                cursor.execute(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'accounts_workorder'
                    AND column_name = '{column_name}'
                """)
                if not cursor.fetchone():
                    missing_columns.append(column_name)

            if missing_columns:
                print(f"❌ Still missing columns: {missing_columns}")
                return False
            else:
                print("✅ All mechanic columns are now present!")
                return True

    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

if __name__ == '__main__':
    success = fix_neon_schema()
    if success:
        print("\n🎉 Schema fix complete!")
        print("📱 Test your mobile app now.")
    else:
        print("\n❌ Schema fix failed.")
        sys.exit(1)
