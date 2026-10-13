from __future__ import annotations

from typing import Sequence

import pandas as pd

from src.ops.pg_upsert import get_pg_connection


def get_yield_data(start_date: str, end_date: str, tickers: Sequence[str]) -> pd.DataFrame:
    """
    Load yield data from PostgreSQL and return a pivoted DataFrame.

    - Index: Date
    - Columns: curve_code (e.g. DGS10, DGS2)
    - Values: yield
    """
    if not tickers:
        empty = pd.DataFrame()
        empty.index.name = "Date"
        return empty

    sql = """
        SELECT date, curve_code, yield
        FROM yields_daily
        WHERE date >= %s
          AND date <= %s
          AND curve_code = ANY(%s)
        ORDER BY date, curve_code
    """

    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (start_date, end_date, list(tickers)))
            rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=["Date", "Ticker", "Yield"])
    if df.empty:
        out = pd.DataFrame(columns=list(tickers))
        out.index.name = "Date"
        return out

    pivot = df.pivot(index="Date", columns="Ticker", values="Yield")
    pivot = pivot.reindex(columns=list(tickers))
    pivot.index.name = "Date"
    return pivot

