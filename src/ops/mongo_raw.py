from __future__ import annotations

import datetime as dt
import os
from typing import Any

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi

from src.utils.hashing import sha256_json


def _dedupe_basis(series_id: str, params: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    # FRED metadata (e.g. realtime_* fields) can change across runs.
    # Use stable fields for dedupe.
    return {
        "source": "FRED",
        "series_id": series_id,
        "observation_start": params.get("observation_start"),
        "observation_end": params.get("observation_end"),
        "observations": payload.get("observations", []),
    }


def get_mongo_db():
    load_dotenv()
    mongo_password = os.getenv("MONGO_PASSWORD")
    if not mongo_password:
        raise RuntimeError("MONGO_PASSWORD is not set. Add it to .env and retry.")
    uri = (
        "mongodb+srv://eujin31_db_user:"
        + mongo_password
        + "@cluster0.r4hyyk6.mongodb.net/?appName=Cluster0"
    )
    db_name = os.getenv("MONGO_DB", "bond_raw")
    client = MongoClient(
        uri,
        server_api=ServerApi("1"),
        tls=True,
        tlsCAFile=certifi.where(),
    )
    return client[db_name]


def ensure_payload_hash_index() -> None:
    db = get_mongo_db()
    collection = db["raw_snapshots"]
    existing_indexes = collection.index_information()
    has_payload_hash_index = False
    for spec in existing_indexes.values():
        keys = spec.get("key", [])
        if len(keys) == 1 and keys[0][0] == "payload_hash":
            has_payload_hash_index = True
            break
    if not has_payload_hash_index:
        collection.create_index("payload_hash", unique=True)


def store_raw_snapshot_if_new(series_id: str, url: str, params: dict[str, Any], payload: dict[str, Any]) -> bool:
    db = get_mongo_db()
    collection = db["raw_snapshots"]
    payload_hash = sha256_json(_dedupe_basis(series_id=series_id, params=params, payload=payload))
    if collection.find_one({"payload_hash": payload_hash}, {"_id": 1}):
        return False

    doc = {
        "source": "FRED",
        "series_id": series_id,
        "request": {"url": url, "params": params},
        "fetched_at": dt.datetime.now(dt.timezone.utc),
        "payload": payload,
        "payload_hash": payload_hash,
    }
    collection.insert_one(doc)
    return True


def upsert_demo_fundamentals(ticker: str, asof_date: str, source: str = "DEMO") -> bool:
    db = get_mongo_db()
    collection = db["fundamentals"]

    doc = {
        "ticker": ticker.upper(),
        "asof_date": asof_date,
        "source": source,
        "company": {
            "name": f"{ticker.upper()} Holdings",
            "sector": "Financials",
            "country": "US",
        },
        "metrics": {
            "valuation": {
                "pe_ttm": 15.3,
                "pb": 1.8,
                # optional metrics may be missing per ticker
                "ev_ebitda": None,
            },
            "profitability": {
                "roe": 0.126,
                "net_margin": 0.211,
            },
            "balance_sheet": {
                "debt_to_equity": 0.44,
                "interest_coverage": None,
            },
        },
        "filings": {
            "latest_10k": {
                "date": "2025-12-31",
                "auditor": "Demo & Co LLP",
            }
        },
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }

    result = collection.update_one(
        {"ticker": doc["ticker"], "asof_date": doc["asof_date"], "source": doc["source"]},
        {"$set": doc},
        upsert=True,
    )
    return result.upserted_id is not None


def get_raw_snapshot_stats() -> tuple[int, int, dt.datetime | None]:
    db = get_mongo_db()
    collection = db["raw_snapshots"]
    total_count = collection.count_documents({})
    distinct_hash_count = len(collection.distinct("payload_hash"))
    latest = collection.find_one({}, sort=[("fetched_at", -1)], projection={"fetched_at": 1, "_id": 0})
    latest_fetched_at = latest.get("fetched_at") if latest else None
    return total_count, distinct_hash_count, latest_fetched_at
