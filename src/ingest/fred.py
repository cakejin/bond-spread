from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

from src.ingest.cache import build_cache_path, load_payload_from_cache, save_payload_to_cache
from src.utils.retry import retry_network

FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"


@dataclass
class FetchedSeries:
    series_id: str
    url: str
    params: dict[str, Any]
    payload: dict[str, Any]
    rows: list[tuple[str, str, float | None]]
    cache_hit: bool = False


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned in {"", "."}:
            return None
        return float(cleaned)
    return float(value)


def _normalize_observations(series_id: str, payload: dict[str, Any]) -> list[tuple[str, str, float | None]]:
    observations = payload.get("observations", [])
    rows: list[tuple[str, str, float | None]] = []
    for item in observations:
        dt = item.get("date")
        if not dt:
            continue
        rows.append((dt, series_id, _to_float_or_none(item.get("value"))))
    return rows


def get_fred_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is not set. Add it to .env and retry.")
    return api_key


def fetch_series(
    series_id: str,
    start_date: str,
    end_date: str,
    timeout: int = 20,
    cache_dir: str = ".cache/fred",
    use_cache: bool = True,
) -> FetchedSeries:
    api_key = get_fred_api_key()
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
    }

    cache_path = build_cache_path(
        cache_dir=cache_dir,
        series_id=series_id,
        start_date=start_date,
        end_date=end_date,
        params=params,
    )

    if use_cache:
        cached = load_payload_from_cache(cache_path)
        if cached is not None:
            rows = _normalize_observations(series_id, cached)
            return FetchedSeries(
                series_id=series_id,
                url=FRED_SERIES_URL,
                params=params,
                payload=cached,
                rows=rows,
                cache_hit=True,
            )

    def _call() -> requests.Response:
        return requests.get(FRED_SERIES_URL, params=params, timeout=timeout)

    response = retry_network(_call, attempts=3, base_sleep=1.0)
    response.raise_for_status()
    payload = response.json()
    if use_cache:
        save_payload_to_cache(cache_path, payload)
    rows = _normalize_observations(series_id, payload)
    return FetchedSeries(
        series_id=series_id,
        url=FRED_SERIES_URL,
        params=params,
        payload=payload,
        rows=rows,
        cache_hit=False,
    )
