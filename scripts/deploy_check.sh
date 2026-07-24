#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_URL:?set PUBLIC_URL}"

python3 scripts/smoke_a2a.py \
  --url "$PUBLIC_URL" \
  --token "${A2A_BEARER_TOKEN:-}" \
  --ticker "600519.SH 多空证据和风险"
curl --fail --silent --show-error "$PUBLIC_URL/healthz" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/.well-known/agent-card.json" >/dev/null
