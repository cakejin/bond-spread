from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

DEFAULT_SERIES = ["DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30"]


def _parse_series(csv_value: str) -> list[str]:
    values = [item.strip() for item in csv_value.split(",") if item.strip()]
    if not values:
        raise ValueError("series value is empty.")
    return values


def _print_series_stats(series_id: str, rows: list[tuple[str, str, float | None]]) -> None:
    null_count = sum(1 for row in rows if row[2] is None)
    if rows:
        dates = [row[0] for row in rows]
        min_date = min(dates)
        max_date = max(dates)
    else:
        min_date = None
        max_date = None
    print(
        f"[{series_id}] fetched={len(rows)} nulls={null_count} "
        f"min_date={min_date} max_date={max_date}"
    )


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _missing_weekdays(rows: list[tuple[str, str, float | None]], start: str, end: str) -> list[str]:
    start_date = _parse_iso_date(start)
    end_date = _parse_iso_date(end)
    observed = {row[0] for row in rows}
    missing: list[str] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            day_str = current.isoformat()
            if day_str not in observed:
                missing.append(day_str)
        current += timedelta(days=1)
    return missing


def cmd_ingest_fred_yields(args: argparse.Namespace) -> int:
    from src.ingest.fred import fetch_series

    try:
        series_ids = _parse_series(args.series)
    except ValueError as exc:
        print(str(exc))
        return 2

    all_rows: list[tuple[str, str, float | None]] = []
    raw_items = []
    per_series_counts = defaultdict(int)

    for series_id in series_ids:
        try:
            fetched = fetch_series(
                series_id=series_id,
                start_date=args.start,
                end_date=args.end,
                cache_dir=args.cache_dir,
                use_cache=not args.no_cache,
            )
        except Exception as exc:
            print(f"[{series_id}] fetch failed: {exc}")
            return 1

        _print_series_stats(series_id, fetched.rows)
        print(f"[{series_id}] source={'cache' if fetched.cache_hit else 'network'}")
        missing = _missing_weekdays(fetched.rows, args.start, args.end)
        if missing:
            preview = ",".join(missing[:10])
            suffix = "..." if len(missing) > 10 else ""
            print(f"[{series_id}] missing_weekdays={len(missing)} dates={preview}{suffix}")
        else:
            print(f"[{series_id}] missing_weekdays=0")
        all_rows.extend(fetched.rows)
        per_series_counts[series_id] += len(fetched.rows)
        raw_items.append(fetched)

    if args.dry_run:
        print(
            f"[dry-run] total_series={len(series_ids)} total_rows={len(all_rows)} "
            f"mongo_raw=skip postgres_upsert=skip"
        )
        return 0

    if args.mongo_raw:
        from src.ops.mongo_raw import ensure_payload_hash_index, store_raw_snapshot_if_new

        ensure_payload_hash_index()
        mongo_inserted = 0
        for item in raw_items:
            inserted = store_raw_snapshot_if_new(
                series_id=item.series_id,
                url=item.url,
                params=item.params,
                payload=item.payload,
            )
            mongo_inserted += 1 if inserted else 0
        print(f"[mongo] inserted_raw_docs={mongo_inserted} deduped={len(raw_items) - mongo_inserted}")
    else:
        print("[mongo] skip (--mongo-raw not set)")

    from src.ops.pg_upsert import ensure_instruments, upsert_yields

    try:
        inserted_instruments = ensure_instruments(series_ids)
        upserted_rows = upsert_yields(all_rows)
    except Exception as exc:
        print(f"[postgres] upsert failed: {exc}")
        return 1

    print(
        f"[postgres] instruments_inserted={inserted_instruments} upsert_rows={upserted_rows} "
        f"series={len(series_ids)}"
    )
    print(f"[summary] per_series_rows={dict(per_series_counts)} total_rows={len(all_rows)}")
    return 0


def cmd_verify_yields(args: argparse.Namespace) -> int:
    from src.ops.pg_upsert import (
        find_yield_jump_outliers,
        verify_yields,
        verify_yields_null_counts,
        verify_yields_overall_null_count,
    )

    try:
        series_ids = _parse_series(args.series)
    except ValueError as exc:
        print(str(exc))
        return 2

    try:
        rows = verify_yields(series_ids)
        null_rows = verify_yields_null_counts(series_ids)
        overall_null_count = verify_yields_overall_null_count(series_ids)
        outliers = find_yield_jump_outliers(series_ids, jump_threshold=0.2)
    except Exception as exc:
        print(f"[verify] query failed: {exc}")
        return 1

    by_code = {code: (count, min_date, max_date) for code, count, min_date, max_date in rows}
    null_by_code = {code: null_count for code, null_count in null_rows}
    counts = []
    for code in series_ids:
        count, min_date, max_date = by_code.get(code, (0, None, None))
        null_count = null_by_code.get(code, 0)
        counts.append(count)
        print(f"[{code}] count={count} nulls={null_count} min_date={min_date} max_date={max_date}")
    print(f"[overall] nulls={overall_null_count}")

    if counts:
        min_count = min(counts)
        max_count = max(counts)
        if min_count == max_count:
            print(f"[consistency] row_count_aligned=yes count={min_count}")
        else:
            print(f"[consistency] row_count_aligned=no min_count={min_count} max_count={max_count}")

    if outliers:
        print(f"[outlier-candidates] count={len(outliers)} threshold=20%")
        for date_str, code, prev_yield, curr_yield, jump_ratio in outliers[:50]:
            pct = jump_ratio * 100.0
            print(
                f"[outlier] date={date_str} series={code} prev={prev_yield:.4f} "
                f"curr={curr_yield:.4f} jump_pct={pct:.2f}"
            )
        if len(outliers) > 50:
            print(f"[outlier-candidates] ... {len(outliers) - 50} more")
    else:
        print("[outlier-candidates] none over 20% day-over-day")
    return 0


def cmd_mongo_demo_fundamentals(args: argparse.Namespace) -> int:
    from src.ops.mongo_raw import upsert_demo_fundamentals

    try:
        inserted = upsert_demo_fundamentals(ticker=args.ticker, asof_date=args.asof, source=args.source)
    except Exception as exc:
        print(f"[mongo] fundamentals upsert failed: {exc}")
        return 1

    action = "inserted" if inserted else "updated"
    print(
        f"[mongo] fundamentals {action} ticker={args.ticker.upper()} "
        f"asof={args.asof} source={args.source}"
    )
    return 0


def cmd_verify_mongo_raw(args: argparse.Namespace) -> int:
    from src.ops.mongo_raw import get_raw_snapshot_stats

    try:
        total_count, distinct_hash_count, latest_fetched_at = get_raw_snapshot_stats()
    except Exception as exc:
        print(f"[verify-mongo-raw] Atlas unreachable or query failed: {exc}")
        return 1

    print(f"[raw_snapshots] count={total_count}")
    print(f"[raw_snapshots] distinct_payload_hash={distinct_hash_count}")
    print(f"[raw_snapshots] latest_fetched_at={latest_fetched_at}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bond-spread data ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_ingest = subparsers.add_parser("ingest-fred-yields", help="Fetch FRED yields and upsert into Postgres")
    p_ingest.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_ingest.add_argument("--end", required=True, help="YYYY-MM-DD")
    p_ingest.add_argument(
        "--series",
        default=",".join(DEFAULT_SERIES),
        help="Comma-separated FRED series IDs (default: DGS3MO,DGS2,DGS5,DGS10,DGS30)",
    )
    p_ingest.add_argument("--mongo-raw", action="store_true", help="Store raw FRED payload to Mongo")
    p_ingest.add_argument("--dry-run", action="store_true", help="Fetch and normalize only")
    p_ingest.add_argument("--cache-dir", default=".cache/fred", help="FRED payload cache directory")
    p_ingest.add_argument("--no-cache", action="store_true", help="Disable cache read/write")
    p_ingest.set_defaults(func=cmd_ingest_fred_yields)

    p_verify = subparsers.add_parser("verify-yields", help="Verify yields_daily coverage by curve_code")
    p_verify.add_argument("--series", required=True, help="Comma-separated FRED series IDs")
    p_verify.set_defaults(func=cmd_verify_yields)

    p_funda = subparsers.add_parser(
        "mongo-demo-fundamentals",
        help="Upsert demo fundamentals document into MongoDB Atlas",
    )
    p_funda.add_argument("--ticker", required=True, help="Ticker symbol")
    p_funda.add_argument("--asof", required=True, help="YYYY-MM-DD")
    p_funda.add_argument("--source", default="DEMO", help="Document source label")
    p_funda.set_defaults(func=cmd_mongo_demo_fundamentals)

    p_verify_mongo = subparsers.add_parser(
        "verify-mongo-raw",
        help="Verify raw_snapshots stats in MongoDB Atlas",
    )
    p_verify_mongo.set_defaults(func=cmd_verify_mongo_raw)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
