#!/usr/bin/env bash
# Expose the local A2A server to the public internet for judging (track 18 命脉:
# "评审期稳定在线 + Agent Card 公网可访问"). Uses Cloudflare Tunnel (quick tunnel).
#
# Usage:  scripts/expose_tunnel.sh [PORT]      (default 8080)
# Then copy the printed https URL into PUBLIC_URL and restart the server so the
# Agent Card advertises the public /a2a endpoint.
#
# NOTE (human step): a named/stable tunnel needs `cloudflared tunnel login` with
# YOUR Cloudflare account. The quick tunnel below needs no login but the URL is
# ephemeral — fine for a rehearsal, use a named tunnel for the real judging slot.
set -euo pipefail
PORT="${1:-8080}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install:"
  echo "  Linux:  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared && chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/"
  echo "  macOS:  brew install cloudflared"
  exit 1
fi

echo "▶ exposing http://localhost:${PORT} via Cloudflare quick tunnel …"
echo "  (copy the https URL below into PUBLIC_URL, then restart the server)"
exec cloudflared tunnel --url "http://localhost:${PORT}"
