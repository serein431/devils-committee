#!/usr/bin/env bash
# One command to run the whole thing (offline demo, zero credentials).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

echo "▶ Devil's Committee — http://localhost:${PORT:-8080}  (Ctrl-C to stop)"
exec .venv/bin/python -m uvicorn backend.a2a_server:app \
  --host "${HOST:-0.0.0.0}" --port "${PORT:-8080}"
