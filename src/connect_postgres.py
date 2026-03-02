import os

from dotenv import load_dotenv
import psycopg

load_dotenv()

conn = psycopg.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=os.getenv("POSTGRES_PORT", "5432"),
    dbname=os.getenv("POSTGRES_DB", "bond_db"),
    user=os.getenv("POSTGRES_USER", "bond_user"),
    password=os.getenv("POSTGRES_PASSWORD", "bond_pass"),
)

with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT version();")
        row = cur.fetchone()
        print("PostgreSQL:", row[0])

        # Simple read check
        cur.execute("SELECT now();")
        print("now():", cur.fetchone()[0])

        cur.execute("SELECT * FROM instruments")
        print("instruments:", cur.fetchall())
