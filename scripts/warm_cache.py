#!/usr/bin/env python3
"""Pre-warm the data cache INSIDE the 7-day panda_data window (service_checklist).

Run this once after DATA_MODE=panda + creds are set, well before judging. It pulls
each demo ticker into ./.cache so the live demo reads from cache even if the window
later expires or rate-limits.

    DATA_MODE=panda python scripts/warm_cache.py 600519.SH 000001.SZ AAPL

No-op-safe: re-running just refreshes tickers not yet cached.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import CONFIG                     # noqa: E402
from backend.skills import cache, data                # noqa: E402

DEFAULT = ["600519.SH", "000001.SZ", "AAPL", "TSLA", "NVDA"]


def main() -> int:
    tickers = sys.argv[1:] or DEFAULT
    if CONFIG.data_mode != "panda":
        print("DATA_MODE is not 'panda' — nothing to warm (mock data is deterministic).")
        print("Set DATA_MODE=panda + creds first (see scripts/setup_real.py).")
        return 0
    ok = 0
    for t in tickers:
        try:
            if cache.is_cached(t):
                print(f"  = {t} already cached"); ok += 1; continue
            bars = data.get_stock_daily(t)
            print(f"  ⬇ {t} -> cached {bars.n} bars ({bars.source})"); ok += 1
        except Exception as e:
            print(f"  ✗ {t}: {str(e)[:120]}")
    print(f"\n{ok}/{len(tickers)} tickers ready in {CONFIG.cache_dir}")
    return 0 if ok == len(tickers) else 1


if __name__ == "__main__":
    sys.exit(main())
