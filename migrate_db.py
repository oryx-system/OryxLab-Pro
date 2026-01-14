"""
Database Migration Script
Adds new columns for the application form fields
"""
import sqlite3
import os

# Database path
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'library.db')

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # List of new columns to add
    new_columns = [
        ("applicant_type", "VARCHAR(10) DEFAULT '개인'"),
        ("org_name", "VARCHAR(100)"),
        ("facility_basic", "VARCHAR(100)"),
        ("facility_extra", "VARCHAR(100)"),
        ("expected_count", "INTEGER"),
        ("birth_date", "VARCHAR(20)"),
        ("address", "VARCHAR(200)"),
        ("email", "VARCHAR(100)")
    ]
    
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE reservation ADD COLUMN {col_name} {col_type}")
            print(f"[OK] Added column: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"[SKIP] Column already exists: {col_name}")
            else:
                print(f"[ERR] Error adding {col_name}: {e}")
    
    conn.commit()
    conn.close()
    print("\n[OK] Migration completed!")

if __name__ == "__main__":
    migrate()
