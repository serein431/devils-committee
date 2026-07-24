#!/usr/bin/env bash
# Clone the real QuantSkills repos used by the debate, for SKILL_MODE=cli.
# Verified repo names on 2026-07-23 (github.com/quantskills).
#
# Usage:  scripts/fetch_quantskills.sh            (clones into ./vendor/quantskills)
# Then set SKILL_MODE=cli and QUANTSKILLS_DIR=./vendor/quantskills in .env.
set -euo pipefail
DEST="${QUANTSKILLS_DIR:-./vendor/quantskills}"
mkdir -p "$DEST"

REPOS=(
  skill-pandadata-api
  skill-corporate-action-adjustment-auditor
  skill-survivorship-universe-auditor
  skill-portfolio-liquidity-stress-test
  skill-index-rebalance-event-study
  skill-factor-ranking-sage
  skill-model-hpo-evidence-driven
)

failed=0
for r in "${REPOS[@]}"; do
  if [ -d "$DEST/$r/.git" ]; then
    echo "↻ $r (pull)"
    if ! git -C "$DEST/$r" pull --quiet; then
      echo "! $r update failed" >&2
      failed=1
    fi
  else
    echo "⬇ $r"
    if ! git clone --quiet "https://github.com/quantskills/$r.git" "$DEST/$r"; then
      echo "! $r clone failed" >&2
      failed=1
    fi
  fi
done
echo "done -> $DEST"
exit "$failed"
