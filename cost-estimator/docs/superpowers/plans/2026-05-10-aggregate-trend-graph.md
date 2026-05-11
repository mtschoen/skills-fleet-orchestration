# Aggregate Trend Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an aggregate cost-trend chart that stacks per-machine spend over an arbitrary date range, closing the "Trend over time beyond daily" gap in `SKILL.md`. Add `CLAUDE_COST_ROOTS` env-var support so multi-machine setups don't have to repeat CLI args.

**Architecture:** New `plot-trend.py` reads `sessions.csv` (no JSONL re-scan), buckets sessions by day/week/month (auto with override), pivots to one Chart.js dataset per machine label, overlays a cumulative-total line on a right y-axis. Multi-root env-var work lives only in `analyze-month.py`; the trend script sees pre-resolved data via the CSV. Chart.js URL/version constants, download caching, and the CDN-vs-inline `<script>` tag builder extract into a thin `chart_runtime.py` shared between `plot-session.py` and `plot-trend.py`.

**Tech Stack:** Python 3.11+, stdlib only (`argparse`, `csv`, `datetime`, `json`, `urllib`, `webbrowser`), Chart.js 4 + chartjs-adapter-date-fns 3 served via CDN or inlined.

---

## File Structure

- `scripts/chart_runtime.py` — new, ~50 lines. Chart.js URL/version constants, `_cached_download()`, `chartjs_script_tags()` helper.
- `scripts/plot-session.py` — modified. Imports the constants and helpers from `chart_runtime`; deletes its own copies.
- `scripts/analyze-month.py` — modified. `_resolve_roots()` helper added; main() consults `CLAUDE_COST_ROOTS` when no positional roots given.
- `scripts/plot-trend.py` — new, ~250 lines. Bucket key generation, CSV filter+pivot, Chart.js HTML template, CLI.
- `scripts/test_buckets.py` — new, ~25 lines. Pure-function unit smoke for bucket-key edges.
- `scripts/test_resolve_roots.py` — new, ~30 lines. Unit smoke for env-var parsing precedence.
- `SKILL.md` — modified. Drop the "Trend over time beyond daily" bullet, document `plot-trend.py` and `CLAUDE_COST_ROOTS`.
- `README.md` — modified. Brief paragraph on the trend chart, link to a sample screenshot.

---

## Phase 1: Extract `chart_runtime.py` and refactor `plot-session.py`

Refactor first so `plot-trend.py` (Phase 3) imports an already-stable module.

### Task 1: Create `chart_runtime.py`

**Files:**
- Create: `scripts/chart_runtime.py`

- [x] **Step 1: Write the module**

```python
"""Shared Chart.js runtime helpers for plot-session.py and plot-trend.py.

Holds the Chart.js + date-fns adapter version constants and the
CDN/inline download plumbing. Each plotter still owns its own HTML
template and chart config; only the bits that would literally
duplicate (and must stay in sync across plotters when Chart.js
updates) live here.
"""

from __future__ import annotations

import sys
from pathlib import Path

CHARTJS_CDN_URL = "https://cdn.jsdelivr.net/npm/chart.js@4"
TIME_ADAPTER_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/"
    "chartjs-adapter-date-fns.bundle.min.js"
)

CHARTJS_INLINE_VERSION = "4.4.7"
CHARTJS_INLINE_URL = (
    f"https://cdn.jsdelivr.net/npm/chart.js@{CHARTJS_INLINE_VERSION}/dist/"
    "chart.umd.min.js"
)
TIME_ADAPTER_INLINE_VERSION = "3.0.0"
TIME_ADAPTER_INLINE_URL = (
    f"https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@{TIME_ADAPTER_INLINE_VERSION}/"
    "dist/chartjs-adapter-date-fns.bundle.min.js"
)


def _cached_download(url: str, cache_filename: str) -> bytes:
    """Return bytes of `url`, caching to ~/.cache/cost-estimator/<cache_filename>."""
    import urllib.request

    cache_directory = Path.home() / ".cache" / "cost-estimator"
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_directory / cache_filename
    if cache_path.is_file():
        return cache_path.read_bytes()
    print(f"  fetching {url} -> {cache_path}", file=sys.stderr)
    with urllib.request.urlopen(url) as response:
        payload = response.read()
    cache_path.write_bytes(payload)
    return payload


def chartjs_script_tags(inline: bool, want_time_adapter: bool) -> tuple[str, str]:
    """Build the (chartjs_script_tag, time_adapter_script_tag) pair.

    With `inline=True`, the returned tags embed the downloaded JS
    bytes directly. With `inline=False`, they reference the CDN URLs.
    If `want_time_adapter=False`, the time adapter tag is the empty
    string.
    """
    if inline:
        chartjs_bytes = _cached_download(
            CHARTJS_INLINE_URL,
            f"chart.js-{CHARTJS_INLINE_VERSION}.umd.min.js",
        )
        chartjs_tag = f"<script>{chartjs_bytes.decode('utf-8')}</script>"
    else:
        chartjs_tag = f'<script src="{CHARTJS_CDN_URL}"></script>'

    if not want_time_adapter:
        return chartjs_tag, ""

    if inline:
        adapter_bytes = _cached_download(
            TIME_ADAPTER_INLINE_URL,
            f"chartjs-adapter-date-fns-{TIME_ADAPTER_INLINE_VERSION}.bundle.min.js",
        )
        adapter_tag = f"<script>{adapter_bytes.decode('utf-8')}</script>"
    else:
        adapter_tag = f'<script src="{TIME_ADAPTER_CDN_URL}"></script>'

    return chartjs_tag, adapter_tag
```

- [x] **Step 2: Verify it imports cleanly**

Run: `python -c "from chart_runtime import chartjs_script_tags; print(chartjs_script_tags(False, False))"`

Expected: prints `('<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>', '')`. Run from `scripts/` directory.

- [x] **Step 3: Commit**

```bash
git add scripts/chart_runtime.py
git commit -m "chart_runtime: shared Chart.js URL constants + script-tag helper"
```

### Task 2: Refactor `plot-session.py` to import from `chart_runtime`

**Files:**
- Modify: `scripts/plot-session.py`

- [x] **Step 1: Capture pre-refactor HTML output for regression check**

```bash
cd scripts
python plot-session.py <some-session-id-prefix> --out /tmp/pre-refactor.html
```

Pick any session-id prefix from the user's recent `sessions.csv` (or use a JSONL path directly). Save the output to `/tmp/pre-refactor.html` (or platform equivalent).

- [x] **Step 2: Replace the duplicated constants + helpers with imports**

In `scripts/plot-session.py`, delete lines 152–180 (the six URL/version constants and `_cached_download`). Replace with:

```python
from chart_runtime import (
    CHARTJS_CDN_URL,                       # noqa: F401  (re-exported for symmetry; chart_runtime uses it)
    CHARTJS_INLINE_VERSION,
    CHARTJS_INLINE_URL,
    TIME_ADAPTER_CDN_URL,                  # noqa: F401  (re-exported for symmetry; chart_runtime uses it)
    TIME_ADAPTER_INLINE_VERSION,
    TIME_ADAPTER_INLINE_URL,
    cached_download,
    chartjs_script_tags,
)
```

Then in `render_html()` (originally lines 244–281), replace the inline CDN-vs-inline tag-building block with:

```python
chartjs_script_tag, time_adapter_script_tag = chartjs_script_tags(
    inline=chartjs_inline_bytes is not None,
    want_time_adapter=(x_axis_mode == "time"),
)
```

The `chartjs_inline_bytes` / `time_adapter_inline_bytes` parameters on `render_html` are now unused. Keep them in the signature (and the `main()` call site) so this task's diff stays surgical; remove in a follow-up if desired. The double-download concern is moot — `_cached_download` reads from cache on the second call, so `main()`'s pre-download just pre-warms the cache that `chartjs_script_tags(inline=True, ...)` then reads.

- [x] **Step 3: Run a session render to verify**

```bash
python plot-session.py <same-session-id-prefix> --out /tmp/post-refactor.html
```

Expected: succeeds.

- [x] **Step 4: Diff pre vs post**

```bash
diff /tmp/pre-refactor.html /tmp/post-refactor.html
```

Expected: empty diff (byte-identical output).

- [x] **Step 5: Test `--inline-js` path**

```bash
python plot-session.py <same-session-id-prefix> --inline-js --out /tmp/post-inline.html
```

Expected: succeeds, HTML is larger (embedded Chart.js bytes), opens in browser standalone.

- [x] **Step 6: Commit**

```bash
git add scripts/plot-session.py
git commit -m "plot-session: route Chart.js script tags through chart_runtime"
```

---

## Phase 2: Add `CLAUDE_COST_ROOTS` env-var resolution to `analyze-month.py`

### Task 3: Write `_resolve_roots()` helper with unit tests

**Files:**
- Modify: `scripts/analyze-month.py`
- Create: `scripts/test_resolve_roots.py`

- [x] **Step 1: Write the failing test**

```python
"""Unit smoke for _resolve_roots() in analyze-month.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    """analyze-month.py has a hyphen; import via spec loader."""
    spec = importlib.util.spec_from_file_location(
        "analyze_month",
        Path(__file__).parent / "analyze-month.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["analyze_month"] = module
    spec.loader.exec_module(module)
    return module


def test_cli_roots_override_env(monkeypatch_env=None):
    am = _load_module()
    pairs = am._resolve_roots(
        cli_roots=["/some/cli/path"],
        cli_labels=["host-a"],
        env_value="chonkers:/x,llamabox:/y",
    )
    assert pairs == [("host-a", Path("/some/cli/path"))]


def test_env_used_when_no_cli():
    am = _load_module()
    pairs = am._resolve_roots(
        cli_roots=[],
        cli_labels=[],
        env_value="chonkers:/x,llamabox:/y",
    )
    assert pairs == [("chonkers", Path("/x")), ("llamabox", Path("/y"))]


def test_default_when_no_cli_no_env():
    am = _load_module()
    pairs = am._resolve_roots(cli_roots=[], cli_labels=[], env_value=None)
    assert len(pairs) == 1
    assert pairs[0][0] == "local"
    assert pairs[0][1] == Path.home() / ".claude" / "projects"


def test_windows_drive_letter_in_env_path():
    """First colon is the delimiter; rest is the path (includes C:)."""
    am = _load_module()
    pairs = am._resolve_roots(
        cli_roots=[], cli_labels=[],
        env_value="chonkers:C:/Users/mtsch/.claude/projects",
    )
    assert pairs == [("chonkers", Path("C:/Users/mtsch/.claude/projects"))]


def test_env_malformed_raises():
    am = _load_module()
    try:
        am._resolve_roots(cli_roots=[], cli_labels=[], env_value="no_colon_entry")
    except SystemExit as exit_info:
        assert "malformed" in str(exit_info.code)
    else:
        raise AssertionError("expected SystemExit")


if __name__ == "__main__":
    test_cli_roots_override_env()
    test_env_used_when_no_cli()
    test_default_when_no_cli_no_env()
    test_windows_drive_letter_in_env_path()
    test_env_malformed_raises()
    print("OK")
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python scripts/test_resolve_roots.py`
Expected: `AttributeError: module 'analyze_month' has no attribute '_resolve_roots'`

- [x] **Step 3: Implement `_resolve_roots()` in `analyze-month.py`**

Add this function above `main()` in `scripts/analyze-month.py`:

```python
def _resolve_roots(cli_roots, cli_labels, env_value):
    """Resolve (label, path) pairs from CLI args + CLAUDE_COST_ROOTS env var.

    Precedence:
      1. CLI roots present  -> use those, ignore env var (print note if env set)
      2. CLI roots empty + env set -> parse env, use those
      3. Both empty -> default to [("local", ~/.claude/projects)]

    Env var format: "label1:path1,label2:path2". The FIRST colon in
    each pair is the delimiter; the rest of the entry is the path
    (so Windows "C:/..." paths work).
    """
    if cli_roots:
        if env_value:
            print("note: CLAUDE_COST_ROOTS set but CLI roots given; using CLI",
                  file=sys.stderr)
        labels = list(cli_labels or [])
        while len(labels) < len(cli_roots):
            labels.append(f"root{len(labels)}")
        return [(labels[i], Path(cli_roots[i])) for i in range(len(cli_roots))]

    if env_value:
        pairs = []
        for entry in env_value.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" not in entry:
                sys.exit(f"error: CLAUDE_COST_ROOTS malformed near '{entry}' "
                         f"(expected 'label:path')")
            label, _, path = entry.partition(":")
            label = label.strip()
            path = path.strip()
            if not label or not path:
                sys.exit(f"error: CLAUDE_COST_ROOTS malformed near '{entry}' "
                         f"(expected 'label:path')")
            pairs.append((label, Path(path)))
        return pairs

    return [("local", Path.home() / ".claude" / "projects")]
```

- [x] **Step 4: Run the test to verify it passes**

Run: `python scripts/test_resolve_roots.py`
Expected: `OK`

- [x] **Step 5: Commit**

```bash
git add scripts/analyze-month.py scripts/test_resolve_roots.py
git commit -m "analyze-month: add _resolve_roots() with CLAUDE_COST_ROOTS support"
```

### Task 4: Wire `_resolve_roots()` into `main()`

**Files:**
- Modify: `scripts/analyze-month.py:218-249` (the `roots = [...]` block and the `for root, label in zip(roots, labels)` loop)

- [x] **Step 1: Replace the existing root-resolution block**

In `analyze-month.py`'s `main()`, replace lines 238–241 (`roots = [Path(...)]` and the labels-padding loop) with:

```python
import os
resolved_roots = _resolve_roots(
    cli_roots=arguments.roots,
    cli_labels=arguments.label,
    env_value=os.environ.get("CLAUDE_COST_ROOTS"),
)
# Validate paths exist before kicking off workers
for label, path in resolved_roots:
    if not path.exists():
        sys.exit(f"error: root not found: {path} (label={label})")
```

Then replace the `for root, label in zip(roots, labels):` loop (line 245) with:

```python
all_files = []
for label, root in resolved_roots:
    files = discover_files(root)
    print(f"[{label}] {root}: {len(files)} jsonl files", file=sys.stderr)
    for path, parent, is_subagent in files:
        all_files.append((path, parent, is_subagent, label))
print(f"Total files: {len(all_files)}", file=sys.stderr)
```

Hoist the `import os` to the top of the file (it's already used elsewhere — check the existing imports and add if absent).

Also: the `roots` argparse positional must now accept zero args. Change `parser.add_argument("roots", nargs="+")` (or whatever the current spec is) to `nargs="*"` so an env-var-only invocation parses cleanly. Verify current syntax by reading `argparse` setup near line 210.

- [x] **Step 2: Smoke test with env var unset**

```bash
unset CLAUDE_COST_ROOTS    # PowerShell: Remove-Item Env:CLAUDE_COST_ROOTS
python scripts/analyze-month.py --month 2026-04
```

Expected: `[local] <home>/.claude/projects: N jsonl files`, runs to completion, writes `reports/sessions.csv`.

- [x] **Step 3: Smoke test with env var set**

```bash
export CLAUDE_COST_ROOTS="local:$HOME/.claude/projects"
# PowerShell: $env:CLAUDE_COST_ROOTS = "local:C:/Users/mtsch/.claude/projects"
python scripts/analyze-month.py --month 2026-04
```

Expected: `[local] <home>/.claude/projects: N jsonl files` (matches step 2 output).

- [x] **Step 4: Smoke test malformed env var**

```bash
export CLAUDE_COST_ROOTS="no_colon"
python scripts/analyze-month.py --month 2026-04
```

Expected: exit code 1, stderr contains `error: CLAUDE_COST_ROOTS malformed near 'no_colon'`.

- [x] **Step 5: Smoke test missing path**

```bash
export CLAUDE_COST_ROOTS="ghost:/nonexistent/path"
python scripts/analyze-month.py --month 2026-04
```

Expected: exit code 1, stderr contains `error: root not found: /nonexistent/path (label=ghost)`.

- [x] **Step 6: Smoke test CLI overrides env**

```bash
export CLAUDE_COST_ROOTS="ghost:/nonexistent/path"
python scripts/analyze-month.py "$HOME/.claude/projects" --label local --month 2026-04
```

Expected: prints `note: CLAUDE_COST_ROOTS set but CLI roots given; using CLI`, then runs successfully against the home path (ignoring the bad env entry).

- [x] **Step 7: Commit**

```bash
git add scripts/analyze-month.py
git commit -m "analyze-month: use _resolve_roots() for CLI+env-var root resolution"
```

---

## Phase 3: Build `plot-trend.py`

### Task 5: Bucket-key function with unit tests

**Files:**
- Create: `scripts/plot-trend.py` (start with just the bucket function + imports)
- Create: `scripts/test_buckets.py`

- [x] **Step 1: Write the failing test**

Create `scripts/test_buckets.py`:

```python
"""Unit smoke for bucket_key() in plot-trend.py."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "plot_trend",
        Path(__file__).parent / "plot-trend.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["plot_trend"] = module
    spec.loader.exec_module(module)
    return module


def test_day_bucket():
    pt = _load_module()
    assert pt.bucket_key(datetime(2026, 4, 12), "day") == "2026-04-12"


def test_month_bucket():
    pt = _load_module()
    assert pt.bucket_key(datetime(2026, 4, 12), "month") == "2026-04"


def test_week_bucket_simple():
    pt = _load_module()
    # 2026-04-13 is a Monday, ISO 2026-W16
    assert pt.bucket_key(datetime(2026, 4, 13), "week") == "2026-W16"


def test_week_bucket_iso_year_boundary():
    """2024-12-30 (Monday) belongs to ISO 2025-W01.

    ISO week 1 is the week containing the first Thursday of the year.
    2025-01-01 is a Wednesday, so first Thursday is 2025-01-02, and
    week 1 starts Mon 2024-12-30.
    """
    pt = _load_module()
    assert pt.bucket_key(datetime(2024, 12, 30), "week") == "2025-W01"


def test_auto_bucket_picker():
    pt = _load_module()
    assert pt.auto_bucket(days=7) == "day"
    assert pt.auto_bucket(days=14) == "day"
    assert pt.auto_bucket(days=15) == "week"
    assert pt.auto_bucket(days=90) == "week"
    assert pt.auto_bucket(days=91) == "month"


if __name__ == "__main__":
    test_day_bucket()
    test_month_bucket()
    test_week_bucket_simple()
    test_week_bucket_iso_year_boundary()
    test_auto_bucket_picker()
    print("OK")
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python scripts/test_buckets.py`
Expected: `FileNotFoundError` or `ModuleNotFoundError` (plot-trend.py doesn't exist yet).

- [x] **Step 3: Implement `bucket_key()` and `auto_bucket()` in a new `plot-trend.py`**

Create `scripts/plot-trend.py`:

```python
"""Render aggregate Claude Code cost trend across sessions as an HTML chart.

Reads sessions.csv (the artifact written by analyze-month.py), buckets
sessions by their first_timestamp into day/week/month bins, stacks the
per-bucket cost by machine label, and overlays a cumulative-total line
on a right y-axis. Visual idiom matches plot-session.py.

Usage:
    python plot-trend.py
        (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD)
        [--bucket {day,week,month}]
        [--csv <path>]
        [--inline-js]
        [--out <path>]
        [--open]
"""

from __future__ import annotations

from datetime import datetime


def bucket_key(timestamp: datetime, granularity: str) -> str:
    """Return a stable string key for grouping by day, week, or month.

    Keys are designed to sort lexically into chronological order so
    `sorted(bucket_set)` in the pivot step yields the right x-axis
    ordering without parsing.

    - day:   "2026-04-12"
    - week:  "YYYY-Www" using ISO week numbering (year may differ from
             timestamp.year near Jan/Dec boundaries)
    - month: "2026-04"  (locale-immune, lexically sortable; display
             formatting like "Apr 2026" happens at render time)
    """
    if granularity == "day":
        return timestamp.strftime("%Y-%m-%d")
    if granularity == "week":
        iso_year, iso_week, _ = timestamp.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "month":
        return timestamp.strftime("%Y-%m")
    raise ValueError(f"unknown granularity: {granularity!r}")


def auto_bucket(days: int) -> str:
    """Pick a bucket granularity from a date-range span."""
    if days <= 14:
        return "day"
    if days <= 90:
        return "week"
    return "month"
```

- [x] **Step 4: Run the test to verify it passes**

Run: `python scripts/test_buckets.py`
Expected: `OK`

- [x] **Step 5: Commit**

```bash
git add scripts/plot-trend.py scripts/test_buckets.py
git commit -m "plot-trend: bucket_key + auto_bucket with unit smoke"
```

### Task 6: CSV reader, range filter, and pivot

**Files:**
- Modify: `scripts/plot-trend.py`

- [x] **Step 1: Add CSV-reading + filtering + pivot helpers**

Append to `scripts/plot-trend.py`:

```python
import csv
from collections import defaultdict
from pathlib import Path


def read_sessions_in_range(csv_path: Path, range_start: datetime,
                           range_end: datetime):
    """Read rows of sessions.csv whose first_timestamp falls in
    [range_start, range_end] (inclusive).

    Boundaries should be NAIVE datetimes (no tzinfo). The CSV stores
    tz-aware timestamps; this function strips tzinfo on parse so the
    range comparison works without the caller needing to know.

    Returns (rows, skipped) where:
      - rows: list of dicts with two extra fields per row:
          "_parsed_timestamp" (datetime, naive) and "_cost_usd_float" (float)
      - skipped: count of rows with missing/unparseable first_timestamp
    """
    rows = []
    skipped = 0
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp_string = row.get("first_timestamp") or ""
            if not timestamp_string:
                skipped += 1
                continue
            try:
                timestamp = datetime.fromisoformat(timestamp_string)
            except ValueError:
                skipped += 1
                continue
            # Drop tzinfo so callers can pass naive boundary datetimes
            # (argparse-derived from "YYYY-MM-DD" strings).
            if timestamp.tzinfo is not None:
                timestamp = timestamp.replace(tzinfo=None)
            if range_start <= timestamp <= range_end:
                row["_parsed_timestamp"] = timestamp
                row["_cost_usd_float"] = float(row.get("cost_usd") or 0)
                rows.append(row)
    return rows, skipped


def pivot_to_datasets(rows: list[dict], granularity: str):
    """Return (bucket_keys_sorted, per_label_datasets, cumulative_dataset,
    per_label_session_counts).

    per_label_datasets: dict[label] = list aligned with bucket_keys_sorted,
    each entry a float cost. Zero-filled where the (label, bucket) had no
    sessions.

    cumulative_dataset: list aligned with bucket_keys_sorted, running
    total across all labels.

    per_label_session_counts: dict[label] = list aligned with
    bucket_keys_sorted, integer session counts (used in tooltips).
    """
    sums = defaultdict(lambda: defaultdict(float))   # sums[label][bucket]
    counts = defaultdict(lambda: defaultdict(int))   # counts[label][bucket]
    bucket_set = set()
    label_set = set()
    for row in rows:
        key = bucket_key(row["_parsed_timestamp"], granularity)
        label = row["label"]
        sums[label][key] += row["_cost_usd_float"]
        counts[label][key] += 1
        bucket_set.add(key)
        label_set.add(label)

    buckets_sorted = sorted(bucket_set)
    labels_sorted = sorted(label_set)
    per_label_costs = {
        label: [round(sums[label].get(bucket, 0.0), 4) for bucket in buckets_sorted]
        for label in labels_sorted
    }
    per_label_counts = {
        label: [counts[label].get(bucket, 0) for bucket in buckets_sorted]
        for label in labels_sorted
    }

    cumulative = []
    running = 0.0
    for bucket in buckets_sorted:
        for label in labels_sorted:
            running += sums[label].get(bucket, 0.0)
        cumulative.append(round(running, 4))

    return buckets_sorted, per_label_costs, cumulative, per_label_counts
```

- [x] **Step 2: Quick interactive smoke**

```bash
cd scripts
python -c "
from datetime import datetime
import plot_trend_module  # via importlib
"
```

(Adapt to importlib loader.) Read a real `sessions.csv`, pass `--month 2026-04` bounds, confirm `read_sessions_in_range` returns >0 rows and `pivot_to_datasets` returns aligned arrays.

A simpler smoke: add this temporary `if __name__ == "__main__":` block at the bottom of `plot-trend.py` and run it directly with a hard-coded path:

```python
if __name__ == "__main__":
    import sys
    csv_path = Path(sys.argv[1])
    start = datetime.fromisoformat(sys.argv[2])
    end = datetime.fromisoformat(sys.argv[3])
    rows, skipped = read_sessions_in_range(csv_path, start, end)
    print(f"rows={len(rows)} skipped={skipped}")
    if rows:
        buckets, per_label, cumulative, counts = pivot_to_datasets(rows, "day")
        print(f"buckets={buckets[:3]}... ({len(buckets)} total)")
        print(f"labels={list(per_label.keys())}")
        print(f"first_label_costs={list(per_label.values())[0][:5]}")
        print(f"cumulative_final=${cumulative[-1]}")
```

Run: `python scripts/plot-trend.py reports/sessions.csv 2026-04-01T00:00:00 2026-04-30T23:59:59`
Expected: nonzero rows, sane bucket count, cumulative roughly matching `summarize.py`'s headline number for April.

- [x] **Step 3: Delete the temporary `__main__` block**

We'll add the real CLI in Task 8.

- [x] **Step 4: Commit**

```bash
git add scripts/plot-trend.py
git commit -m "plot-trend: CSV range filter and per-label pivot"
```

### Task 7: HTML render

**Files:**
- Modify: `scripts/plot-trend.py`

- [x] **Step 1: Add the HTML template and `render_html()` function**

Append to `scripts/plot-trend.py`:

```python
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).parent))
from chart_runtime import chartjs_script_tags  # noqa: E402

PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
]


def _label_color(label: str) -> str:
    """Stable color from label hash; collides past 8 distinct labels."""
    digest = hashlib.md5(label.encode("utf-8")).digest()
    return PALETTE[digest[0] % len(PALETTE)]


# Filled via str.format(). Literal `{` / `}` in JS/CSS doubled to `{{` / `}}`.
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trend {range_label}</title>
{chartjs_script_tag}
<style>
  html, body {{ height: 100%; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 12px; color: #222; }}
  h1 {{ margin: 0 0 8px 0; font-size: 18px; }}
  .meta {{ font-family: ui-monospace, "Cascadia Mono", Menlo, monospace;
          font-size: 12px; color: #555; margin-bottom: 16px; }}
  .meta span {{ display: inline-block; margin-right: 18px; }}
  .chart-wrap {{ position: relative; width: 100%; height: 70vh; min-height: 420px; }}
  canvas {{ width: 100% !important; height: 100% !important; }}
  .footnote {{ font-size: 11px; color: #888; margin-top: 12px; }}
</style>
</head>
<body>
<h1>Cost trend — {range_label}</h1>
<div class="meta">
  <span>Bucket: {bucket_granularity}</span>
  <span>Total: ${total_cost:.4f}</span>
  <span>Sessions: {total_sessions}</span>
  <span>Machines: {machines_summary}</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas></div>
<div class="footnote">
  Aggregates per-session costs from sessions.csv; subagent costs are folded
  into their parent session's total (no separate subagent series).
</div>
<script>
const BUCKETS = {buckets_json};
const PER_LABEL_COSTS = {per_label_costs_json};
const PER_LABEL_COUNTS = {per_label_counts_json};
const PER_LABEL_COLORS = {per_label_colors_json};
const CUMULATIVE = {cumulative_json};

const labels = Object.keys(PER_LABEL_COSTS);
const datasets = labels.map(label => ({{
  type: "bar",
  label: label,
  data: PER_LABEL_COSTS[label],
  backgroundColor: PER_LABEL_COLORS[label],
  borderColor: PER_LABEL_COLORS[label],
  stack: "cost",
  yAxisID: "y",
}}));
datasets.push({{
  type: "line",
  label: "Cumulative",
  data: CUMULATIVE,
  borderColor: "#333",
  backgroundColor: "rgba(0,0,0,0)",
  borderWidth: 2,
  tension: 0.2,
  pointRadius: 0,
  yAxisID: "y1",
}});

new Chart(document.getElementById("chart"), {{
  data: {{ labels: BUCKETS, datasets: datasets }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, type: "category" }},
      y: {{ stacked: true, position: "left", beginAtZero: true,
           title: {{ display: true, text: "Cost ($)" }} }},
      y1: {{ position: "right", beginAtZero: true,
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: "Cumulative ($)" }} }},
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          afterLabel: (item) => {{
            if (item.dataset.type !== "bar") return "";
            const label = item.dataset.label;
            const count = PER_LABEL_COUNTS[label][item.dataIndex];
            return `${{count}} session${{count === 1 ? "" : "s"}}`;
          }},
        }},
      }},
    }},
  }},
}});
</script>
</body>
</html>
"""


def render_html(*, range_label: str, bucket_granularity: str,
                buckets: list[str], per_label_costs: dict,
                per_label_counts: dict, cumulative: list[float],
                inline: bool) -> str:
    chartjs_script_tag, _ = chartjs_script_tags(inline=inline,
                                                want_time_adapter=False)
    total_cost = cumulative[-1] if cumulative else 0.0
    total_sessions = sum(sum(counts) for counts in per_label_counts.values())
    per_label_totals = {
        label: (round(sum(costs), 2), sum(per_label_counts[label]))
        for label, costs in per_label_costs.items()
    }
    machines_summary = ", ".join(
        f"{label} (${cost:.2f}, {count})"
        for label, (cost, count) in sorted(per_label_totals.items())
    )
    per_label_colors = {label: _label_color(label) for label in per_label_costs}

    return HTML_TEMPLATE.format(
        range_label=range_label,
        bucket_granularity=bucket_granularity,
        total_cost=total_cost,
        total_sessions=total_sessions,
        machines_summary=machines_summary or "(none)",
        chartjs_script_tag=chartjs_script_tag,
        buckets_json=json.dumps(buckets).replace("</", "<\\/"),
        per_label_costs_json=json.dumps(per_label_costs).replace("</", "<\\/"),
        per_label_counts_json=json.dumps(per_label_counts).replace("</", "<\\/"),
        per_label_colors_json=json.dumps(per_label_colors).replace("</", "<\\/"),
        cumulative_json=json.dumps(cumulative).replace("</", "<\\/"),
    )
```

- [x] **Step 2: Commit**

```bash
git add scripts/plot-trend.py
git commit -m "plot-trend: HTML template, Chart.js config, stable label colors"
```

### Task 8: CLI wiring + main()

**Files:**
- Modify: `scripts/plot-trend.py`

- [x] **Step 1: Append `main()` and the `if __name__` guard**

Append to `scripts/plot-trend.py`:

```python
import argparse
import webbrowser

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent / "reports" / "sessions.csv"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "reports"


def _month_bounds(month_string: str) -> tuple[datetime, datetime]:
    year, month = (int(part) for part in month_string.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end.replace(microsecond=0)  # exclusive upper handled inclusively below


def _date_bounds(start_string: str, end_string: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(start_string)
    end = datetime.fromisoformat(end_string).replace(hour=23, minute=59, second=59)
    return start, end


def main():
    parser = argparse.ArgumentParser(
        description="Render aggregate cost trend as an HTML chart."
    )
    range_group = parser.add_mutually_exclusive_group(required=True)
    range_group.add_argument("--month", help="YYYY-MM")
    range_group.add_argument("--start", help="YYYY-MM-DD start (requires --end)")
    parser.add_argument("--end", help="YYYY-MM-DD end (inclusive)")
    parser.add_argument("--bucket", choices=("day", "week", "month"),
                        default=None,
                        help="Bucket size (default: auto from range length)")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH),
                        help=f"sessions.csv path (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--inline-js", action="store_true")
    parser.add_argument("--out", default=None,
                        help=f"Output HTML path (default: {DEFAULT_OUT_DIR}/trend-<range>.html)")
    parser.add_argument("--open", dest="open_browser", action="store_true")
    arguments = parser.parse_args()

    if arguments.month:
        range_start, range_end = _month_bounds(arguments.month)
        # _month_bounds gives exclusive upper; convert to inclusive end-of-prev-day
        range_end = range_end.replace(hour=0, minute=0, second=0)
        range_label = arguments.month
        range_filename = arguments.month
        span_days = (range_end - range_start).days
    else:
        if not arguments.end:
            parser.error("--start requires --end")
        range_start, range_end = _date_bounds(arguments.start, arguments.end)
        range_label = f"{arguments.start} → {arguments.end}"
        range_filename = f"{arguments.start}_{arguments.end}"
        span_days = (range_end - range_start).days + 1

    granularity = arguments.bucket or auto_bucket(span_days)
    print(f"Range: {range_start.isoformat()} -> {range_end.isoformat()}",
          file=sys.stderr)
    print(f"Bucket: {granularity} (span={span_days} days)", file=sys.stderr)

    csv_path = Path(arguments.csv)
    if not csv_path.is_file():
        sys.exit(f"error: sessions.csv not found at {csv_path}. "
                 f"Run analyze-month.py first, or pass --csv <path>.")

    rows, skipped = read_sessions_in_range(csv_path, range_start, range_end)
    if not rows:
        # Probe overall span for a helpful error message
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            total_rows = 0
            min_ts = None
            max_ts = None
            for row in reader:
                total_rows += 1
                ts_string = row.get("first_timestamp") or ""
                if not ts_string:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_string)
                except ValueError:
                    continue
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts
        span_message = (f"{min_ts.isoformat()}...{max_ts.isoformat()}"
                        if min_ts else "(no parseable rows)")
        sys.exit(f"error: no sessions in range {range_start.date()} -> "
                 f"{range_end.date()} (csv has {total_rows} rows total, "
                 f"span {span_message}).")

    if skipped:
        print(f"note: skipped {skipped} rows with unparseable first_timestamp",
              file=sys.stderr)

    buckets, per_label_costs, cumulative, per_label_counts = pivot_to_datasets(
        rows, granularity,
    )

    html_text = render_html(
        range_label=range_label,
        bucket_granularity=granularity,
        buckets=buckets,
        per_label_costs=per_label_costs,
        per_label_counts=per_label_counts,
        cumulative=cumulative,
        inline=arguments.inline_js,
    )

    if arguments.out:
        output_path = Path(arguments.out)
    else:
        output_path = DEFAULT_OUT_DIR / f"trend-{range_filename}.html"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)

    if arguments.open_browser:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
```

- [x] **Step 2: End-to-end smoke for `--month`**

```bash
python scripts/plot-trend.py --month 2026-04 --open
```

Expected:
- HTML opens in default browser
- Stacked bars per day (auto-picked because April is 30 days), one stack color per machine label in `sessions.csv`
- Cumulative line on right y-axis
- Hover tooltip shows label + dollar amount + "N sessions"
- Meta row's total matches `summarize.py`'s headline for the same range

- [x] **Step 3: Smoke `--bucket week` and `--bucket month`**

```bash
python scripts/plot-trend.py --month 2026-04 --bucket week --out reports/trend-april-week.html
python scripts/plot-trend.py --month 2026-04 --bucket month --out reports/trend-april-month.html
```

Expected: both succeed; week-bucketed chart has ~5 bars, month-bucketed has 1.

- [x] **Step 4: Smoke `--start`/`--end`**

```bash
python scripts/plot-trend.py --start 2026-04-15 --end 2026-04-21 --open
```

Expected: 7 daily bars (auto-picked), correct range_label in title.

- [x] **Step 5: Smoke `--inline-js`**

```bash
python scripts/plot-trend.py --month 2026-04 --inline-js --out /tmp/trend-offline.html
```

Open `/tmp/trend-offline.html` in a browser with network disabled. Expected: chart renders identically.

- [x] **Step 6: Smoke missing CSV**

```bash
python scripts/plot-trend.py --month 2026-04 --csv /nonexistent/sessions.csv
```

Expected: exit 1, error message `error: sessions.csv not found at ...`.

- [x] **Step 7: Smoke empty range**

```bash
python scripts/plot-trend.py --start 2099-01-01 --end 2099-01-31
```

Expected: exit 1, error message includes `csv has N rows total, span <real-min>...<real-max>`.

- [x] **Step 8: Cross-validate against `summarize.py`**

```bash
python scripts/analyze-month.py --month 2026-04   # if not already run
python scripts/summarize.py | grep -i total       # capture summarize total
python scripts/plot-trend.py --month 2026-04 --out /tmp/april.html
grep -o 'Total: \$[0-9.]*' /tmp/april.html
```

Expected: dollar amounts match. If they diverge, math is wrong — diagnose before declaring done.

- [x] **Step 9: Commit**

```bash
git add scripts/plot-trend.py
git commit -m "plot-trend: CLI wiring, range bounds, end-to-end smoke passes"
```

---

## Phase 4: Docs

### Task 9: Update `SKILL.md`

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: Drop the "Trend over time beyond daily" bullet**

In `SKILL.md`'s "What this skill does not do (yet)" section, delete:

```markdown
- Trend over time beyond daily. No weekly / month-over-month deltas.
```

- [ ] **Step 2: Add a step in the main flow**

After the existing `plot-session.py` step (step 5), insert:

```markdown
6. **Plot the aggregate trend across the range.** Run after
   analyze-month.py so the CSV exists:
   ```bash
   python <skill-root>/scripts/plot-trend.py \
       (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD) \
       [--bucket {day,week,month}] [--inline-js] [--open]
   ```
   Produces an HTML chart at `<skill-root>/reports/trend-<range>.html`.
   Bars stack per-machine cost in each bucket; right-axis line shows
   the cumulative total. Bucket size auto-picks from range length
   (≤14d→day, ≤90d→week, >90d→month) or override with `--bucket`.
```

Renumber subsequent steps. The "Offer to save" step is now step 7.

- [ ] **Step 3: Document `CLAUDE_COST_ROOTS` in the inputs section**

In the "Inputs to gather from the user" section, under "Projects roots", add:

```markdown
   Multi-machine setups can set the `CLAUDE_COST_ROOTS` env var once
   (format: `"label1:path1,label2:path2"`) — analyze-month.py picks it
   up automatically when no positional roots are given. CLI args
   always win when both are present.
```

- [ ] **Step 4: Add `plot-trend.py` to "Files in this skill"**

After the `plot-session.py` entry:

```markdown
- `scripts/plot-trend.py` — aggregate trend chart across sessions.csv
  (uses `chart_runtime.py`). Stacks by machine label.
- `scripts/chart_runtime.py` — shared Chart.js URL/version constants,
  download cache, and script-tag helper used by both plot scripts.
```

- [ ] **Step 5: Commit**

```bash
git add SKILL.md
git commit -m "skill: document plot-trend.py and CLAUDE_COST_ROOTS"
```

### Task 10: Update `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a paragraph on the trend chart**

After the existing `plot-session.py` section, append:

```markdown
### Trend across sessions

After running `analyze-month.py` for the range you care about, render
the aggregate trend:

```bash
python scripts/plot-trend.py --month 2026-04 --open
```

Stacked bars show per-machine cost in each bucket (day / week / month,
auto-picked from range length or set with `--bucket`). The right-axis
line is the cumulative total. Multi-machine setups can pre-set
`CLAUDE_COST_ROOTS="chonkers:C:/Users/you/.claude/projects,llamabox:Y:/.claude/projects"`
so `analyze-month.py` picks up every root without repeating CLI args.
```

(Skip the screenshot for now — add it after the first real run as a follow-up.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "readme: document plot-trend.py and CLAUDE_COST_ROOTS"
```

---

## Final verification

Before considering the work done:

- [ ] `python scripts/test_resolve_roots.py` passes
- [ ] `python scripts/test_buckets.py` passes
- [ ] `plot-session.py` produces byte-identical HTML pre vs post chart_runtime extraction
- [ ] `plot-trend.py --month <recent>` total matches `summarize.py` total for the same range
- [ ] At least one `--inline-js` chart opens correctly with network disabled
- [ ] Error cases (missing CSV, empty range, malformed env var, missing path) all exit with a clear stderr message
