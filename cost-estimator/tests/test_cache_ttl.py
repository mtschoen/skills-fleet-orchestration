"""Unit test for the pure gap-bucketing logic in scripts/cache_ttl.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import cache_ttl  # noqa: E402


def test_bucket_for_boundaries():
    # buckets are half-open [lo, hi): 0-1m, 1-5m, 5-10m, 10-20m, 20-60m, >60m
    assert cache_ttl.bucket_for(0) == "0-1m"
    assert cache_ttl.bucket_for(59) == "0-1m"
    assert cache_ttl.bucket_for(60) == "1-5m"
    assert cache_ttl.bucket_for(299) == "1-5m"
    assert cache_ttl.bucket_for(300) == "5-10m"
    assert cache_ttl.bucket_for(3599) == "20-60m"
    assert cache_ttl.bucket_for(3600) == ">60m"
    assert cache_ttl.bucket_for(10 ** 8) == ">60m"


if __name__ == "__main__":
    test_bucket_for_boundaries()
    print("OK")
