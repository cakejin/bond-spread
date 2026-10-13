# Data Pipeline (FRED Yields)

## Series
- `DGS3MO`
- `DGS2`
- `DGS5`
- `DGS10`
- `DGS30`

## Normalization
- Input: FRED `series/observations` payload
- Output row: `(date, curve_code, yield)`
- `value` in `"."`, `""`, `null` => `yield = NULL`
- Numeric text => `float`

## Ingestion Cache
- Scope: collection layer cache for FRED payloads
- Default cache directory: `.cache/fred/`
- Key basis: `series_id`, `observation_start`, `observation_end`, and request params
- Behavior:
  - cache hit + `--no-cache` not set => load payload from cache (no network call)
  - cache miss => fetch from FRED and save cache file
  - `--no-cache` => disable cache read/write

## Mongo Raw Snapshot (Optional)
- Trigger: `--mongo-raw`
- Connection: same Atlas style as `src/connect_mongo.py`
- Collection: `bond_raw.raw_snapshots`
- Document:
  - `source: "FRED"`
  - `series_id`
  - `request: { url, params }`
  - `fetched_at` (UTC datetime)
  - `payload` (raw json)
  - `payload_hash`
- Dedupe:
  - skip insert if same `payload_hash` already exists
  - create `payload_hash` unique index only if missing

## Mongo Fundamentals Demo
- Collection: `bond_raw.fundamentals`
- Command writes flexible nested dict document
- Upsert key: `(ticker, asof_date, source)`
- Document intentionally contains optional/missing fields (`None`) to demonstrate schema flexibility

## PostgreSQL Upsert Policy
- `instruments(code, category, source)`:
  - `INSERT ... ON CONFLICT (code) DO NOTHING`
- `yields_daily(date, curve_code, yield)`:
  - `INSERT ... ON CONFLICT (date, curve_code) DO UPDATE SET yield = EXCLUDED.yield`

## CLI Examples
```bash
python -m src.cli ingest-fred-yields --start 2024-01-01 --end 2024-12-31 --series DGS3MO,DGS2,DGS5,DGS10,DGS30
python -m src.cli ingest-fred-yields --start 2024-01-01 --end 2024-12-31 --series DGS3MO,DGS2,DGS5,DGS10,DGS30 --cache-dir .cache/fred
python -m src.cli ingest-fred-yields --start 2024-01-01 --end 2024-12-31 --series DGS3MO,DGS2,DGS5,DGS10,DGS30 --no-cache
python -m src.cli ingest-fred-yields --start 2024-01-01 --end 2024-12-31 --series DGS3MO,DGS2,DGS5,DGS10,DGS30 --mongo-raw

python -m src.cli verify-yields --series DGS3MO,DGS2,DGS5,DGS10,DGS30
python -m src.cli verify-mongo-raw
python -m src.cli mongo-demo-fundamentals --ticker TLT --asof 2026-03-04
```

