"""Local data cache for the 7-day panda_data window (service_checklist 要求).

Pull the demo tickers ONCE inside the 7-day access window, land them on disk, and
serve from cache during judging — so a window expiry or rate-limit can never break
the live demo. Plain JSON via stdlib (no DuckDB/parquet dep needed); the format is
trivial to swap for parquet later if size matters.

Only used when DATA_MODE=panda. Mock data is deterministic and needs no cache.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from ..config import CONFIG


def _path(symbol: str) -> str:
    safe = symbol.replace("/", "_").replace("\\", "_")
    return os.path.join(CONFIG.cache_dir, "bars", f"{safe}.json")


def load(symbol: str) -> Optional[dict]:
    """Return cached bar dict for `symbol`, or None if not cached."""
    p = _path(symbol)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save(symbol: str, payload: dict) -> None:
    """Persist a bar dict for `symbol` (creates the cache dir tree)."""
    p = _path(symbol)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, p)          # atomic: a crash mid-write never corrupts the cache


def is_cached(symbol: str) -> bool:
    return os.path.exists(_path(symbol))
