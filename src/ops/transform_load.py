from __future__ import annotations

import argparse
import datetime as dt
import math
import re
from collections import defaultdict

from src.ops.mongo_raw import get_mongo_db
from src.ops.pg_upsert import ensure_instruments, get_pg_connection

DEFAULT_SERIES = ["DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30"]
MISSING_MARKERS = {"", ".", "NA", "N/A", "NULL", "NONE", "-"}
NUMERIC_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def _strict_to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError(f"invalid numeric value: {value}")
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.upper() in MISSING_MARKERS:
            return None
        if NUMERIC_RE.fullmatch(cleaned):
            return float(cleaned)
    raise ValueError(f"cannot convert to float: {value!r}")


def _ensure_updated_at_column() -> None:
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE yields_daily
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
                """
            )


def _load_raw_rows(
    series_ids: list[str],
    start_date: str | None,
    end_date: str | None,
) -> tuple[list[tuple[str, str, float | None]], int]:
    db = get_mongo_db()
    collection = db["raw_snapshots"]

    query = {"source": "FRED", "series_id": {"$in": series_ids}}
    docs = list(collection.find(query).sort("fetched_at", 1))

    by_key: dict[tuple[str, str], float | None] = {}
    bad_values = 0

    for doc in docs:
        series_id = doc.get("series_id")
        payload = doc.get("payload", {})
        observations = payload.get("observations", [])
        for obs in observations:
            date_str = obs.get("date")
            if not date_str or not series_id:
                continue
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            try:
                val = _strict_to_float(obs.get("value"))
            except ValueError:
                bad_values += 1
                continue
            by_key[(date_str, series_id)] = val

    rows = [(d, s, v) for (d, s), v in sorted(by_key.items())]
    return rows, bad_values


def _find_missing_tenors(
    rows: list[tuple[str, str, float | None]],
    series_ids: list[str],
) -> dict[str, list[str]]:
    date_to_series: dict[str, set[str]] = defaultdict(set)
    for date_str, curve_code, _ in rows:
        date_to_series[date_str].add(curve_code)

    missing: dict[str, list[str]] = {}
    for date_str, existing in sorted(date_to_series.items()):
        miss = [sid for sid in series_ids if sid not in existing]
        if miss:
            missing[date_str] = miss
    return missing


def _interpolate_missing_values(
    rows: list[tuple[str, str, float | None]],
    series_ids: list[str],
) -> tuple[list[tuple[str, str, float | None]], int]:
    values: dict[str, dict[str, float | None]] = defaultdict(dict)
    all_dates: set[str] = set()
    for date_str, code, val in rows:
        values[code][date_str] = val
        all_dates.add(date_str)

    sorted_dates = sorted(all_dates)
    filled = 0

    for code in series_ids:
        code_map = values[code]
        for idx, date_str in enumerate(sorted_dates):
            if date_str in code_map and code_map[date_str] is not None:
                continue

            prev_idx = idx - 1
            next_idx = idx + 1
            prev_point = None
            next_point = None

            while prev_idx >= 0:
                d = sorted_dates[prev_idx]
                v = code_map.get(d)
                if v is not None:
                    prev_point = (d, v)
                    break
                prev_idx -= 1

            while next_idx < len(sorted_dates):
                d = sorted_dates[next_idx]
                v = code_map.get(d)
                if v is not None:
                    next_point = (d, v)
                    break
                next_idx += 1

            if not prev_point or not next_point:
                continue

            prev_date = dt.date.fromisoformat(prev_point[0]).toordinal()
            next_date = dt.date.fromisoformat(next_point[0]).toordinal()
            cur_date = dt.date.fromisoformat(date_str).toordinal()
            if next_date == prev_date:
                continue

            ratio = (cur_date - prev_date) / (next_date - prev_date)
            interp = prev_point[1] + (next_point[1] - prev_point[1]) * ratio
            code_map[date_str] = float(interp)
            filled += 1

    out_rows: list[tuple[str, str, float | None]] = []
    for code in series_ids:
        for date_str in sorted_dates:
            if date_str in values[code]:
                out_rows.append((date_str, code, values[code][date_str]))
    return out_rows, filled


def _upsert_yields_with_updated_at(rows: list[tuple[str, str, float | None]]) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO yields_daily (date, curve_code, yield, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (date, curve_code)
        DO UPDATE SET
            yield = EXCLUDED.yield,
            updated_at = EXCLUDED.updated_at
    """
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transform Mongo raw_snapshots and load into Postgres yields_daily"
    )
    parser.add_argument(
        "--series",
        default=",".join(DEFAULT_SERIES),
        help="Comma-separated FRED series IDs",
    )
    parser.add_argument("--start", default=None, help="Optional YYYY-MM-DD lower bound")
    parser.add_argument("--end", default=None, help="Optional YYYY-MM-DD upper bound")
    parser.add_argument(
        "--interpolate-missing",
        action="store_true",
        help="Fill missing tenor/date points using linear interpolation",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write to Postgres")
    args = parser.parse_args()

    series_ids = [s.strip() for s in args.series.split(",") if s.strip()]
    if not series_ids:
        print("series value is empty.")
        return 2

    try:
        raw_rows, bad_values = _load_raw_rows(series_ids, args.start, args.end)
    except Exception as exc:
        print(f"[transform-load] failed to read Mongo raw_snapshots: {exc}")
        return 1

    missing = _find_missing_tenors(raw_rows, series_ids)
    print(f"[transform-load] raw_rows={len(raw_rows)} bad_values_skipped={bad_values}")
    if missing:
        print(f"[transform-load] dates_with_missing_tenors={len(missing)}")
        preview_items = list(missing.items())[:10]
        for date_str, miss in preview_items:
            print(f"[missing] date={date_str} missing={','.join(miss)}")
        if len(missing) > 10:
            print(f"[missing] ... {len(missing) - 10} more dates")
    else:
        print("[transform-load] no missing tenor dates found")

    final_rows = raw_rows
    if args.interpolate_missing:
        final_rows, filled = _interpolate_missing_values(raw_rows, series_ids)
        print(f"[transform-load] interpolated_points={filled}")
    else:
        print("[transform-load] interpolation=off")

    if args.dry_run:
        print(f"[dry-run] final_rows={len(final_rows)} postgres_write=skip")
        return 0

    try:
        ensure_instruments(series_ids)
        _ensure_updated_at_column()
        upserted = _upsert_yields_with_updated_at(final_rows)
    except Exception as exc:
        print(f"[transform-load] failed to upsert Postgres yields_daily: {exc}")
        return 1

    print(f"[transform-load] postgres_upsert_rows={upserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

