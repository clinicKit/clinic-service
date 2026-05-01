"""
Migration: Add trial period fields to clinics table
"""
import sqlite3
from pathlib import Path

def migrate():
    # Use default database path
    db_path = Path(__file__).parent.parent / "clinic.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(clinics)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'trial_start_date' not in columns:
            print("Adding trial_start_date column...")
            cursor.execute("ALTER TABLE clinics ADD COLUMN trial_start_date TEXT")
        
        if 'trial_end_date' not in columns:
            print("Adding trial_end_date column...")
            cursor.execute("ALTER TABLE clinics ADD COLUMN trial_end_date TEXT")
        
        if 'is_active' not in columns:
            print("Adding is_active column...")
            cursor.execute("ALTER TABLE clinics ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        
        conn.commit()
        print("Migration completed successfully!")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
