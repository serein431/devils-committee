#!/usr/bin/env python3
"""Pre-warm traceable PandaData bundles for the three public examples.

This script prints only dataset names, row counts, source modes and shortened
content hashes. It never prints PandaData credentials, request headers or raw
service responses.
"""
from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.research_request import ResearchRequest  # noqa: E402
from backend.skills.panda import build_market_data_bundle  # noqa: E402


DEFAULT = ["600519.SH", "300750.SZ", "601318.SH"]
START_DATE = os.environ.get("WARM_CACHE_START", "20240101")
END_DATE = os.environ.get("WARM_CACHE_END", "20260724")


def _request(symbol: str) -> ResearchRequest:
    return ResearchRequest(
        symbol=symbol,
        market="cn",
        question="cache warm-up",
        start_date=START_DATE,
        end_date=END_DATE,
    )


def main() -> int:
    tickers = sys.argv[1:] or DEFAULT
    ready = 0
    for symbol in tickers:
        try:
            bundle = build_market_data_bundle(_request(symbol))
        except Exception:
            print(f"{symbol}: error")
            continue

        print(f"{symbol}: {bundle.status}")
        for name, artifact in sorted(bundle.datasets.items()):
            print(
                f"  {name}: {artifact.rows} rows, {artifact.mode}, "
                f"{artifact.sha256[:8]}"
            )
        if bundle.status == "success" and "daily" in bundle.datasets:
            ready += 1
        else:
            print("  daily: unavailable")

    return 0 if ready == len(tickers) else 1


if __name__ == "__main__":
    raise SystemExit(main())
