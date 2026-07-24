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
  skill-factor-ranking-sage
  skill-residual-guided-factor-selection
  skill-us-sector-rotation
  skill-portfolio-liquidity-stress-test
  skill-index-rebalance-event-study
  skill-holder-structure-scan
  skill-dalio-all-weather
  skill-templeton-global-contrarian
  skill-corporate-action-adjustment-auditor
  skill-survivorship-universe-auditor
  skill-intraday-data-quality-auditor
  skill-model-hpo-evidence-driven
)

for r in "${REPOS[@]}"; do
  if [ -d "$DEST/$r/.git" ]; then
    echo "↻ $r (pull)"; git -C "$DEST/$r" pull --quiet || true
  else
    echo "⬇ $r"; git clone --quiet "https://github.com/quantskills/$r.git" "$DEST/$r" || \
      echo "  (clone failed — repo may be private/renamed; confirm in Feishu)"
  fi
done
echo "done -> $DEST"
