#!/usr/bin/env bash
# Run the jsdom frontend DOM test (verifies web/index.html renders correctly).
# Installs jsdom into a local, gitignored node_modules on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! node -e "require('jsdom')" 2>/dev/null; then
  echo "installing jsdom (first run)…"
  [ -f package.json ] || echo '{"name":"devils-committee-fe-tests","private":true}' > package.json
  npm install --no-audit --no-fund --loglevel=error jsdom
fi

exec node tests/frontend.test.mjs
