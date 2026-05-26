#!/usr/bin/env bash
# Regenerate cost-estimator README screenshots from the synthetic fixture.
#
# Produces screenshot-trend.png and screenshot-compare.png at repo root.
# Run from any cwd; resolves paths relative to this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURE="$REPO_ROOT/tests/fixtures/sessions-demo.csv"
DEMO_RANGE="2026-03"

cd "$REPO_ROOT"

echo "[1/4] rendering plot-trend HTML"
python scripts/plot-trend.py \
    --month "$DEMO_RANGE" \
    --csv "$FIXTURE" \
    --inline-js \
    --out "reports/_trend-demo.html"

echo "[2/4] rendering plot-compare HTML"
python scripts/plot-compare.py \
    --month "$DEMO_RANGE" \
    --csv "$FIXTURE" \
    --inline-js \
    --out "reports/_compare-demo.html"

echo "[3/4] capturing screenshot-trend.png"
python dev/capture-screenshot.py \
    "reports/_trend-demo.html" \
    "screenshot-trend.png"

echo "[4/4] capturing screenshot-compare.png"
python dev/capture-screenshot.py \
    "reports/_compare-demo.html" \
    "screenshot-compare.png"

# Clean up intermediate HTML (reports/ is gitignored but tidy)
rm -f reports/_trend-demo.html reports/_compare-demo.html

echo "done. screenshots at $REPO_ROOT/screenshot-{trend,compare}.png"
