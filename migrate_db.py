import sqlite3
import os

db_path = os.path.join('instance', 'library.db')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

try:
    cur.execute("ALTER TABLE reservation ADD COLUMN checkout_photo TEXT")
    print("Column added successfully.")
except sqlite3.OperationalError as e:
    print(f"Column already exists or error: {e}")

conn.commit()
conn.close()
