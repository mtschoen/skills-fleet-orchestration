# Screenshot automation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate regeneration of the two missing cost-estimator README screenshots (`screenshot-trend.png`, `screenshot-compare.png`) via headless Chrome + a thin Python wrapper, fed by a synthetic fixture CSV so demo charts are stable across regens.

**Architecture:** Headless Chrome CLI with `--virtual-time-budget=5000` so Chart.js animations complete before snap. Thin Python wrapper handles cross-OS Chrome detection and absolute-path normalization. Orchestrator shell + batch scripts feed `tests/fixtures/sessions-demo.csv` through the existing `plot-trend.py` / `plot-compare.py` and snap the resulting HTML to `screenshot-*.png` at the cost-estimator repo root. New tooling is dev-only (excluded from `install-skills` so it doesn't ship with the installed skill).

**Tech Stack:** Python stdlib (argparse, subprocess, pathlib, os, csv, random), bash + cmd.exe, Google Chrome (headless mode). No new pip deps.

---

## Cross-cutting context

Two repos are touched:

1. **`cost-estimator/` submodule** — new scripts, fixture, screenshots, README edits.
2. **`skills-dev/` umbrella** — `install-skills.{sh,bat}` exclusion-list edits, then pointer bump.

Paths in this plan are absolute from the umbrella repo root unless otherwise noted. CWD switches are called out explicitly.

Existing relevant code:

- `cost-estimator/scripts/plot-trend.py` — accepts `--month YYYY-MM --csv <path> --inline-js --out <path>`. Reads `label`, `first_timestamp`, `cost_usd` from sessions.csv.
- `cost-estimator/scripts/plot-compare.py` — same flags, auto-derives prior window.
- `cost-estimator/screenshot.png` — existing per-session screenshot, 1760×1440 (2× retina at 880×720 logical). This plan matches that convention.
- `skills-dev/install-skills.sh` — uses `ROOT_EXCLUDES=(...)` flat list applied via `tar --exclude`.
- `skills-dev/install-skills.bat` — uses `EXCLUDE_DIRS` + `EXCLUDE_FILES` separate lists applied via `robocopy /XD /XF`.

Watch-outs (from spec, repeated here so they're in scope during each phase):

- Absolute path required for Chrome's `--screenshot=` (resolves relative to Chrome install dir on Windows).
- `--disable-gpu` required on Windows or stderr fills with GPU-init noise.
- `--inline-js` non-negotiable — without it the HTML references the Chart.js CDN which won't be reachable in headless mode.
- If snap comes back blank, bump `--virtual-time-budget` to 8000 or 10000.

---

## Phase 1: capture-screenshot.py

### Task 1: Implement `scripts/capture-screenshot.py`

**Files:**
- Create: `cost-estimator/scripts/capture-screenshot.py`

- [x] **Step 1: Write the file**

```python
#!/usr/bin/env python3
"""Render an HTML file to a PNG via headless Chrome.

Locates Chrome via the CHROME_PATH env var (override) or a short list
of OS-specific candidate paths. Uses --virtual-time-budget so Chart.js
animations complete before the screenshot fires.

Usage:
    python capture-screenshot.py <input.html> <output.png>
        [--width 880] [--height 720] [--scale 2] [--budget-ms 5000]

Default dimensions produce a 1760x1440 PNG (2x retina at 880x720
logical), matching the existing screenshot.png convention.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CHROME_CANDIDATES = [
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


def locate_chrome() -> str:
    override = os.environ.get("CHROME_PATH")
    if override:
        if not Path(override).is_file():
            sys.exit(f"error: CHROME_PATH={override!r} does not exist")
        return override
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    sys.exit(
        "error: could not locate Chrome. Set CHROME_PATH or install Chrome "
        f"to one of: {CHROME_CANDIDATES}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input_html", help="Path to the HTML file to render")
    parser.add_argument("output_png", help="Path to write the PNG (absolute or relative)")
    parser.add_argument("--width", type=int, default=880,
                        help="Logical viewport width (default: 880)")
    parser.add_argument("--height", type=int, default=720,
                        help="Logical viewport height (default: 720)")
    parser.add_argument("--scale", type=int, default=2,
                        help="Device scale factor (default: 2 for retina)")
    parser.add_argument("--budget-ms", type=int, default=5000,
                        help="Virtual time budget in ms (default: 5000)")
    arguments = parser.parse_args()

    input_path = Path(arguments.input_html).resolve()
    if not input_path.is_file():
        sys.exit(f"error: input HTML not found: {input_path}")
    output_path = Path(arguments.output_png).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chrome = locate_chrome()
    url = input_path.as_uri()  # produces file:///... on Windows + POSIX

    command = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={arguments.width},{arguments.height}",
        f"--force-device-scale-factor={arguments.scale}",
        f"--virtual-time-budget={arguments.budget_ms}",
        f"--screenshot={output_path}",
        url,
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(f"error: chrome exited {result.returncode}")
    if not output_path.is_file():
        sys.exit(f"error: chrome reported success but {output_path} not written")
    print(f"wrote {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Render a smoke HTML against real sessions.csv**

(We don't have the fixture yet — use the existing real data for the smoke.)

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/plot-trend.py --month 2026-04 --inline-js --out reports/_smoke.html
```

Expected stderr: `Range: 2026-04-01 -> ...` and bucket info. `reports/_smoke.html` should be created (~150KB with inline Chart.js).

- [x] **Step 3: Smoke capture-screenshot on the produced HTML**

```bash
python scripts/capture-screenshot.py reports/_smoke.html /tmp/smoke.png
```

Expected stdout: `wrote /tmp/smoke.png (NNNNN bytes)`. No stderr noise.

- [x] **Step 4: Verify PNG dimensions**

```bash
python -c "from PIL import Image; im=Image.open('/tmp/smoke.png'); print(im.size, im.mode)"
```

Expected: `(1760, 1440) RGB` (or RGBA — both fine).

- [x] **Step 5: Visually inspect the PNG**

Open `/tmp/smoke.png` in an image viewer. Confirm:
- Bars are visible (NOT blank canvas — that's the timing-budget failure mode; bump `--budget-ms 10000` if so)
- Axis labels are readable
- Legend renders

If blank: re-run Step 3 with `--budget-ms 10000`. Document the working value.

- [x] **Step 6: Clean up smoke artifacts**

```bash
rm reports/_smoke.html /tmp/smoke.png
```

- [x] **Step 7: Commit**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
git add scripts/capture-screenshot.py
git commit -m "$(cat <<'EOF'
scripts: add capture-screenshot.py (headless Chrome wrapper)

Thin Python wrapper around Chrome's --headless --screenshot. Locates
Chrome via CHROME_PATH env override or an OS-specific candidate list
(Windows / macOS / Linux). Uses --virtual-time-budget=5000 so
Chart.js animations finish before the snap fires.

Defaults to 880x720 logical viewport at 2x device-scale-factor,
producing a 1760x1440 PNG that matches the existing screenshot.png
convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: Synthetic fixture CSV

### Task 2: Generate and commit `tests/fixtures/sessions-demo.csv`

**Files:**
- Create: `cost-estimator/tests/fixtures/sessions-demo.csv`

The fixture is produced by a one-off seeded generator. The generator is not committed — only its output is.

- [x] **Step 1: Write the generator (one-off, not committed)**

```bash
mkdir -p C:/Users/mtsch/skills-dev/cost-estimator/tests/fixtures
```

Write `/tmp/gen_demo_fixture.py`:

```python
"""One-off generator for tests/fixtures/sessions-demo.csv.

Seeded random; output is deterministic. Covers Feb + March 2026 across
two synthetic hosts, with chonkers carrying the bulk of spend.
"""
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(20260511)

HEADER = [
    "label", "session_date", "session_id", "first_timestamp",
    "last_timestamp", "cost_usd", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "cache_hit_pct",
    "first_turn_input_tokens", "assistant_turns", "user_turns",
    "subagent_count", "subagent_cost", "had_compact", "models",
    "top_tools", "parent_path",
]
EMPTY_COLS = [c for c in HEADER if c not in {
    "label", "session_date", "session_id", "first_timestamp",
    "last_timestamp", "cost_usd",
}]

HOSTS = [
    # (label, sessions/day distribution, cost-scale multiplier)
    ("chonkers", [0.20, 0.45, 0.25, 0.10], 1.5),
    ("llamabox", [0.55, 0.35, 0.10, 0.00], 0.7),
]

day_start = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
day_end = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)

rows = []
sid = 0
current = day_start
while current <= day_end:
    for label, weights, scale in HOSTS:
        n = random.choices([0, 1, 2, 3], weights=weights)[0]
        for _ in range(n):
            sid += 1
            timestamp = current + timedelta(
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            duration_hours = random.randint(1, 8)
            cost = round(random.uniform(5, 300) * scale, 4)
            row = {col: "" for col in HEADER}
            row.update({
                "label": label,
                "session_date": timestamp.date().isoformat(),
                "session_id": f"fake-{sid:04d}",
                "first_timestamp": timestamp.isoformat(),
                "last_timestamp": (timestamp + timedelta(hours=duration_hours)).isoformat(),
                "cost_usd": f"{cost}",
            })
            rows.append(row)
    current += timedelta(days=1)

out = Path("C:/Users/mtsch/skills-dev/cost-estimator/tests/fixtures/sessions-demo.csv")
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

print(f"wrote {out} ({len(rows)} rows)")
```

- [x] **Step 2: Run the generator**

```bash
python /tmp/gen_demo_fixture.py
```

Expected stdout: `wrote ...sessions-demo.csv (N rows)` where N is roughly 100-150 (60 days × 2 hosts × mean ~1 session each).

- [x] **Step 3: Delete the generator**

```bash
rm /tmp/gen_demo_fixture.py
```

(One-off; if you ever need to regenerate, this plan's git history has the source. Don't carry it forward in the tree.)

- [x] **Step 4: Smoke plot-trend against the fixture**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/plot-trend.py --month 2026-03 --csv tests/fixtures/sessions-demo.csv --inline-js --out reports/_smoke-trend.html
```

Expected stderr: `Range: 2026-03-01 -> 2026-03-31` and bucket info. `reports/_smoke-trend.html` should be created.

- [x] **Step 5: Smoke plot-compare against the fixture**

```bash
python scripts/plot-compare.py --month 2026-03 --csv tests/fixtures/sessions-demo.csv --inline-js --out reports/_smoke-compare.html
```

Expected stderr should show both `Current rows: N` and `Prior rows: M` both > 0 (March = current, February = prior; both populated by the fixture).

- [x] **Step 6: Visually open both HTMLs in a browser**

Confirm both render real bars (not empty charts). The PoP overlay should show March bars vs February bars side by side.

- [x] **Step 7: Clean up smoke HTML**

```bash
rm reports/_smoke-trend.html reports/_smoke-compare.html
```

- [x] **Step 8: Commit the fixture**

```bash
git add tests/fixtures/sessions-demo.csv
git commit -m "$(cat <<'EOF'
fixtures: synthetic sessions data for demo screenshots

Seeded-random hand-curated dataset covering Feb + March 2026 across
two synthetic hosts (chonkers/llamabox). Drives plot-trend and
plot-compare for README screenshot regeneration without snapshotting
real spend.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: regen-screenshots orchestrator

### Task 3: Implement `scripts/regen-screenshots.sh`

**Files:**
- Create: `cost-estimator/scripts/regen-screenshots.sh`

- [ ] **Step 1: Write the file**

```bash
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
python scripts/capture-screenshot.py \
    "reports/_trend-demo.html" \
    "screenshot-trend.png"

echo "[4/4] capturing screenshot-compare.png"
python scripts/capture-screenshot.py \
    "reports/_compare-demo.html" \
    "screenshot-compare.png"

# Clean up intermediate HTML (reports/ is gitignored but tidy)
rm -f reports/_trend-demo.html reports/_compare-demo.html

echo "done. screenshots at $REPO_ROOT/screenshot-{trend,compare}.png"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x C:/Users/mtsch/skills-dev/cost-estimator/scripts/regen-screenshots.sh
```

- [ ] **Step 3: Run it**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
bash scripts/regen-screenshots.sh
```

Expected stdout (4 steps); both PNGs should be created at repo root.

- [ ] **Step 4: Verify outputs**

```bash
ls -la screenshot-trend.png screenshot-compare.png
python -c "from PIL import Image; [print(p, Image.open(p).size) for p in ('screenshot-trend.png','screenshot-compare.png')]"
```

Expected: both files >50KB, both 1760×1440.

- [ ] **Step 5: Visually inspect both PNGs**

Open in an image viewer. Confirm:
- `screenshot-trend.png` shows daily bars for March 2026 with chonkers/llamabox stack and cumulative line
- `screenshot-compare.png` shows March vs February grouped bars + twin cumulative lines

If either is blank canvas: bump budget. Edit `scripts/regen-screenshots.sh` to pass `--budget-ms 10000` to each `capture-screenshot.py` call.

### Task 4: Implement `scripts/regen-screenshots.bat` (with CRLF)

**Files:**
- Create: `cost-estimator/scripts/regen-screenshots.bat`

cmd.exe's `:label` parser requires CRLF line endings on Windows. The Write tool emits LF on Windows — see `feedback_write_tool_lf_windows.md`. Plan compensates by explicitly converting after write.

- [ ] **Step 1: Write the file (LF — will be converted in next step)**

```batch
@echo off
rem Regenerate cost-estimator README screenshots from the synthetic fixture.
rem Produces screenshot-trend.png and screenshot-compare.png at repo root.

setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "REPO_ROOT=%SCRIPT_DIR%\.."
set "FIXTURE=%REPO_ROOT%\tests\fixtures\sessions-demo.csv"
set "DEMO_RANGE=2026-03"

pushd "%REPO_ROOT%"

echo [1/4] rendering plot-trend HTML
python scripts\plot-trend.py --month %DEMO_RANGE% --csv "%FIXTURE%" --inline-js --out reports\_trend-demo.html
if errorlevel 1 goto :error

echo [2/4] rendering plot-compare HTML
python scripts\plot-compare.py --month %DEMO_RANGE% --csv "%FIXTURE%" --inline-js --out reports\_compare-demo.html
if errorlevel 1 goto :error

echo [3/4] capturing screenshot-trend.png
python scripts\capture-screenshot.py reports\_trend-demo.html screenshot-trend.png
if errorlevel 1 goto :error

echo [4/4] capturing screenshot-compare.png
python scripts\capture-screenshot.py reports\_compare-demo.html screenshot-compare.png
if errorlevel 1 goto :error

del reports\_trend-demo.html reports\_compare-demo.html 2>nul

echo done. screenshots at %REPO_ROOT%\screenshot-trend.png and screenshot-compare.png
popd
endlocal
exit /b 0

:error
popd
endlocal
echo regen-screenshots.bat failed (errorlevel %errorlevel%) 1>&2
exit /b 1
```

- [ ] **Step 2: Convert LF -> CRLF**

```bash
sed -i 's/$/\r/' C:/Users/mtsch/skills-dev/cost-estimator/scripts/regen-screenshots.bat
```

- [ ] **Step 3: Run it from Windows cmd**

```bash
cmd.exe /c "cd /d C:\Users\mtsch\skills-dev\cost-estimator && scripts\regen-screenshots.bat"
```

Expected: 4-step output, both PNGs regenerated. (Should overwrite the PNGs from Task 3 with bit-identical content since input is the same.)

- [ ] **Step 4: Verify both PNGs still 1760×1440 + visible bars**

```bash
python -c "from PIL import Image; [print(p, Image.open(p).size) for p in ('C:/Users/mtsch/skills-dev/cost-estimator/screenshot-trend.png', 'C:/Users/mtsch/skills-dev/cost-estimator/screenshot-compare.png')]"
```

Expected: `(1760, 1440)` for each.

### Task 5: Commit screenshots + orchestrators

- [ ] **Step 1: Commit**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
git add scripts/regen-screenshots.sh scripts/regen-screenshots.bat \
        screenshot-trend.png screenshot-compare.png
git commit -m "$(cat <<'EOF'
scripts: regen-screenshots orchestrator + initial PNGs

scripts/regen-screenshots.{sh,bat} produce screenshot-trend.png and
screenshot-compare.png from the synthetic fixture (Feb+March 2026)
via plot-trend / plot-compare into capture-screenshot. Both 1760x1440
to match the existing screenshot.png convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: README updates

### Task 6: Embed screenshots + update Files list

**Files:**
- Modify: `cost-estimator/README.md`

Two embeds, five new entries in `## Files`.

- [ ] **Step 1: Add screenshot-trend embed after "Trend across sessions" section**

In `cost-estimator/README.md`, after the existing block:

```markdown
Stacked bars show per-machine cost in each bucket (day / week / month,
auto-picked from range length or set with `--bucket`). The right-axis
line is the cumulative total. Multi-machine setups can pre-set
`CLAUDE_COST_ROOTS="chonkers:C:/Users/you/.claude/projects,llamabox:Y:/.claude/projects"`
so `analyze-month.py` picks up every root without repeating CLI args.
```

…insert a blank line, then:

```markdown
![Aggregate cost trend across sessions](screenshot-trend.png)
```

- [ ] **Step 2: Add screenshot-compare embed after "Comparing two windows" section**

After the existing block:

```markdown
The prior window is auto-derived (no second range to specify). The chart
shows grouped bars (current vs prior side by side) per bucket and twin
cumulative lines on a right axis. Bucket-index makes paired bars
apples-to-apples wall-clock-relative slices — Day 1 covers the first 24h
of each window, not the same calendar date.
```

…insert blank line, then:

```markdown
![Current vs prior window comparison](screenshot-compare.png)
```

- [ ] **Step 3: Extend `## Files` list with new entries**

The current list ends with `- `.gitignore` — keeps reports and CSV outputs out of git.`. Insert the new entries after the `scripts/trend_data.py` line (the last `scripts/*` entry) and before `reports/`:

```markdown
- `scripts/capture-screenshot.py` — headless Chrome wrapper used by
  the screenshot regen scripts. Dev-only (excluded from `install-skills`).
- `scripts/regen-screenshots.{sh,bat}` — orchestrator that regenerates
  the README PNGs by running plot-trend + plot-compare against the
  demo fixture and capturing each to a 1760x1440 PNG. Dev-only.
- `tests/fixtures/sessions-demo.csv` — synthetic two-host two-month
  sessions data used by `regen-screenshots`. Dev-only.
- `screenshot-trend.png`, `screenshot-compare.png` — README screenshots
  regenerated by `scripts/regen-screenshots`.
```

- [ ] **Step 4: Render-check the README**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
# Verify both image paths exist at the repo root (the embed paths resolve
# relative to README.md location):
ls screenshot-trend.png screenshot-compare.png
```

Expected: both listed. (Browser/GitHub will render the embeds against these paths.)

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: embed trend + compare screenshots in README

Adds image embeds to the "Trend across sessions" and "Comparing two
windows" sections; extends ## Files list with the five new artifacts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: install-skills exclusions (umbrella repo)

This phase edits the umbrella `skills-dev` repo, not cost-estimator.

### Task 7: Update `install-skills.sh`

**Files:**
- Modify: `skills-dev/install-skills.sh:38-43` (the `ROOT_EXCLUDES` array)

- [ ] **Step 1: Add `tests` + the three filenames to `ROOT_EXCLUDES`**

Existing array body:
```bash
ROOT_EXCLUDES=(
    .git .gitignore .gitmodules .github
    README.md AUDIT.md LICENSE HANDOFF.md
    docs evals node_modules reports
    skill-draft
)
```

Replace with:
```bash
ROOT_EXCLUDES=(
    .git .gitignore .gitmodules .github
    README.md AUDIT.md LICENSE HANDOFF.md
    docs evals node_modules reports tests
    skill-draft
    capture-screenshot.py regen-screenshots.sh regen-screenshots.bat
)
```

(`tar --exclude=<name>` matches either filename or directory name at any path depth; no glob needed.)

### Task 8: Update `install-skills.bat`

**Files:**
- Modify: `skills-dev/install-skills.bat:44-45` (the `EXCLUDE_DIRS` + `EXCLUDE_FILES` env vars)

- [ ] **Step 1: Add `tests` to `EXCLUDE_DIRS`**

Current:
```batch
set "EXCLUDE_DIRS=.git .github docs evals node_modules reports skill-draft"
```

Replace with:
```batch
set "EXCLUDE_DIRS=.git .github docs evals node_modules reports skill-draft tests"
```

- [ ] **Step 2: Add the three filenames to `EXCLUDE_FILES`**

Current:
```batch
set "EXCLUDE_FILES=.git .gitignore .gitmodules README.md AUDIT.md LICENSE HANDOFF.md"
```

Replace with:
```batch
set "EXCLUDE_FILES=.git .gitignore .gitmodules README.md AUDIT.md LICENSE HANDOFF.md capture-screenshot.py regen-screenshots.sh regen-screenshots.bat"
```

### Task 9: Verify exclusions in a dry-run

- [ ] **Step 1: Dry-run install-skills.sh against cost-estimator**

```bash
cd C:/Users/mtsch/skills-dev
./install-skills.sh -n cost-estimator
```

Expected behavior:
- If cost-estimator is already installed at `~/.claude/skills/cost-estimator/`, the diff output should NOT mention `tests/`, `capture-screenshot.py`, `regen-screenshots.sh`, or `regen-screenshots.bat`. It may mention the new screenshot PNGs (those DO ship — they're referenced by the SKILL's README and any user wanting to view the installed README will need them). Actually screenshots are at repo root and aren't excluded, so they ship — that's fine.
- If not installed, the dry-run output is just `install cost-estimator -> ~/.claude/skills/cost-estimator`.

(Optional check: do an actual install to a temp dir and `find` for the excluded files to confirm absence.)

- [ ] **Step 2: Sanity-check that screenshot PNGs are NOT excluded**

```bash
cd C:/Users/mtsch/skills-dev
# Confirm screenshot-*.png is not in the exclude list:
grep -E "screenshot" install-skills.sh install-skills.bat
```

Expected: no matches. (We want PNGs to ship so the installed README renders.)

### Task 10: Commit umbrella exclusions

- [ ] **Step 1: Commit**

```bash
cd C:/Users/mtsch/skills-dev
git add install-skills.sh install-skills.bat
git commit -m "$(cat <<'EOF'
install-skills: exclude cost-estimator screenshot regen tooling

Adds tests/ to dir excludes and capture-screenshot.py,
regen-screenshots.sh, regen-screenshots.bat to file excludes for
the root layout. Keeps dev-only screenshot regen out of the
installed skill while still shipping the README screenshots
themselves.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6: Cleanup + ship

### Task 11: Delete the handoff doc

The handoff doc has served its purpose (spec + screenshots now exist). Per spec lifecycle.

- [ ] **Step 1: Remove the handoff**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
git rm docs/superpowers/2026-05-11-screenshot-automation-handoff.md
git commit -m "$(cat <<'EOF'
docs: remove screenshot-automation handoff after ship

The handoff's job (carry context across the session boundary) is done;
spec + screenshots now exist. History remains in git.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 12: Bump umbrella pointer + push

- [ ] **Step 1: Bump pointer**

```bash
cd C:/Users/mtsch/skills-dev
COST_SHA=$(git -C cost-estimator rev-parse --short HEAD)
git add cost-estimator
git commit -m "bump: cost-estimator -> $COST_SHA (screenshot automation + README embeds)"
```

- [ ] **Step 2: Push everything via push-all.bat**

```bash
cmd.exe /c "cd /d C:\Users\mtsch\skills-dev && scripts\push-all.bat"
```

Expected: cost-estimator pushed to Gitea + GitHub; umbrella pushed to Gitea + GitHub. Both report `up-to-date` or `pushed N commits` for each remote with no error summary at the end.

- [ ] **Step 3: Final verification**

```bash
git -C C:/Users/mtsch/skills-dev status
git -C C:/Users/mtsch/skills-dev/cost-estimator status
```

Expected: both clean.

---

## Out of scope (verbatim from spec)

- CI-checked screenshot regression tests (would need `pillow` perceptual diffing — future work).
- Animated-GIF mode (would need `puppeteer-frame-recorder` or similar; requires Node.js).
- Regenerating `screenshot.png` (per-session chart) — left manual unless user asks.
