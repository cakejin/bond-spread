from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _stable_params(params: dict[str, Any]) -> dict[str, Any]:
    return {k: params[k] for k in sorted(params.keys())}


def build_cache_path(
    cache_dir: str | Path,
    series_id: str,
    start_date: str,
    end_date: str,
    params: dict[str, Any],
) -> Path:
    stable = _stable_params(params)
    params_blob = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(params_blob.encode("utf-8")).hexdigest()[:16]
    filename = f"{series_id}_{start_date}_{end_date}_{digest}.json"
    return Path(cache_dir) / filename


def load_payload_from_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_payload_to_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

