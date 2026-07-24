"""QuantSkills + panda_data integration layer.

Verified against the real github.com/quantskills org on 2026-07-23:
  - skills are CLI tools: `python scripts/<name>.py --input data.csv --out report.json`
  - panda_data==0.0.12 exposes get_stock_daily(symbol=[...], start_date, end_date, ...)

`runner.py` invokes them (mock JSON now, subprocess later); `data.py` wraps
panda_data with a DuckDB/Parquet cache; `contracts.py` holds the JSON shapes.
"""

__all__ = ["runner", "data", "contracts"]
