#!/usr/bin/env bash
# Run all unit tests in cost-estimator/scripts. Exits non-zero on first failure.
set -euo pipefail
cd "$(dirname "$0")"
python test_buckets.py
python test_roots.py
python test_compare.py
python test_stats_cache.py
python test_cache_ttl.py
echo "All tests passed."
