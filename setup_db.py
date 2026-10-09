"""Create demo staff/admin accounts in the configured PostgreSQL database.
Run after schema.sql. Uses PGDATABASE=canteen_db_new by default.
"""
import os
import psycopg2
from werkzeug.security import generate_password_hash

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "canteen_db_new"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", ""),
)
accounts = [
    ("STAFF001", "Canteen Staff", "staff", "staff123"),
    ("ADMIN001", "Canteen Admin", "admin", "admin123"),
]
try:
    with conn:
        with conn.cursor() as cur:
            for code, name, role, password in accounts:
                cur.execute(
                    """INSERT INTO staff(staff_code, name, role, password_hash)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (staff_code) DO NOTHING""",
                    (code, name, role, generate_password_hash(password)),
                )
    print("Demo accounts ready:")
    print("Staff: STAFF001 / staff123")
    print("Admin: ADMIN001 / admin123")
    print("Change these demo passwords before real use.")
finally:
    conn.close()
