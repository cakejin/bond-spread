from __future__ import annotations

import os

from dotenv import load_dotenv
import psycopg


def get_pg_connection() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "bond_db"),
        user=os.getenv("POSTGRES_USER", "bond_user"),
        password=os.getenv("POSTGRES_PASSWORD", "bond_pass"),
    )


def ensure_instruments(series_ids: list[str]) -> int:
    insert_sql = """
        INSERT INTO instruments (code, category, source)
        VALUES (%s, %s, %s)
        ON CONFLICT (code) DO NOTHING
    """
    inserted = 0
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            for code in series_ids:
                cur.execute(insert_sql, (code, "yield", "FRED"))
                inserted += cur.rowcount
    return inserted


def upsert_yields(rows: list[tuple[str, str, float | None]]) -> int:
    if not rows:
        return 0

    upsert_sql = """
        INSERT INTO yields_daily (date, curve_code, yield)
        VALUES (%s, %s, %s)
        ON CONFLICT (date, curve_code)
        DO UPDATE SET yield = EXCLUDED.yield
    """
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(upsert_sql, rows)
    return len(rows)


def verify_yields(series_ids: list[str]) -> list[tuple[str, int, str | None, str | None]]:
    sql = """
        SELECT
            curve_code,
            COUNT(*) AS row_count,
            MIN(date)::text AS min_date,
            MAX(date)::text AS max_date
        FROM yields_daily
        WHERE curve_code = ANY(%s)
        GROUP BY curve_code
        ORDER BY curve_code
    """
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (series_ids,))
            return list(cur.fetchall())


def verify_yields_null_counts(series_ids: list[str]) -> list[tuple[str, int]]:
    sql = """
        SELECT
            curve_code,
            COUNT(*) AS null_count
        FROM yields_daily
        WHERE curve_code = ANY(%s)
          AND yield IS NULL
        GROUP BY curve_code
        ORDER BY curve_code
    """
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (series_ids,))
            return list(cur.fetchall())


def verify_yields_overall_null_count(series_ids: list[str]) -> int:
    sql = """
        SELECT COUNT(*)::int
        FROM yields_daily
        WHERE curve_code = ANY(%s)
          AND yield IS NULL
    """
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (series_ids,))
            row = cur.fetchone()
            return row[0] if row else 0


def find_yield_jump_outliers(
    series_ids: list[str],
    jump_threshold: float = 0.2,
) -> list[tuple[str, str, float, float, float]]:
    sql = """
        WITH ordered AS (
            SELECT
                date,
                curve_code,
                yield,
                LAG(yield) OVER (PARTITION BY curve_code ORDER BY date) AS prev_yield
            FROM yields_daily
            WHERE curve_code = ANY(%s)
        )
        SELECT
            date::text AS date,
            curve_code,
            prev_yield::float8 AS prev_yield,
            yield::float8 AS curr_yield,
            ABS((yield - prev_yield) / prev_yield)::float8 AS jump_ratio
        FROM ordered
        WHERE prev_yield IS NOT NULL
          AND yield IS NOT NULL
          AND prev_yield <> 0
          AND ABS((yield - prev_yield) / prev_yield) >= %s
        ORDER BY jump_ratio DESC, curve_code, date
    """
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (series_ids, jump_threshold))
            return list(cur.fetchall())
