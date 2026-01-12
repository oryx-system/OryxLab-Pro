import sqlite3
import os

db_path = os.path.join('instance', 'library.db')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

try:
    # Add signature_blob column (BLOB)
    cur.execute("ALTER TABLE reservation ADD COLUMN signature_blob BLOB")
    print("Column 'signature_blob' added successfully.")
except sqlite3.OperationalError as e:
    print(f"Column already exists or error: {e}")

conn.commit()
conn.close()
