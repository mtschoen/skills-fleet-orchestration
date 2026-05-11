# Screenshot automation — design

**Date:** 2026-05-11
**Status:** approved by user, ready for plan-writing
**Historical context:** `../2026-05-11-screenshot-automation-handoff.md` (prior-session handoff that originated the tool decision and concrete steps; this spec captures the diffs that came out of brainstorming)

---

## Goal

Automate regeneration of the two missing README screenshots — `screenshot-trend.png` (for plot-trend.py) and `screenshot-compare.png` (for plot-compare.py) — so future chart-styling changes regenerate the PNGs in one command instead of manual browser screenshotting.

## Architecture

Headless Chrome CLI + thin Python wrapper. Chosen over Playwright/Puppeteer because the cost-estimator skill is stdlib-only Python today; pulling in a ~150MB Chromium bundle for one dev-only screenshot script is not warranted. Headless Chrome's `--virtual-time-budget` flag fast-forwards Chart.js animation completion before the screenshot fires (web search 2026-05-11 confirms this remains the canonical approach for animated-canvas pages).

## Components

### 1. `scripts/capture-screenshot.py` (~80 lines)

Headless Chrome wrapper.

- argparse for input HTML path + output PNG path + optional `--width / --height / --scale / --budget-ms`
- Locates Chrome via `CHROME_PATH` env var (override) → `CHROME_CANDIDATES` list (try each, take first that exists):
  - Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`
  - macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
  - Linux: `/usr/bin/google-chrome`, fallback `/usr/bin/chromium-browser`
- Defaults: `width=880`, `height=720`, `scale=2`, `budget_ms=5000` → produces 1760×1440 PNG (matches existing `screenshot.png` convention — 2× retina at 880×720 logical viewport)
- Converts input path to absolute `file:///` URL (Chrome's `--screenshot=` interprets relative paths against its install dir on Windows)
- Subprocess invocation with stdout+stderr captured; non-zero exit → print stderr and `sys.exit`

Chrome flags used:
```
--headless
--disable-gpu               # avoid GPU init noise on headless Windows
--hide-scrollbars           # cosmetic
--window-size=<W>,<H>
--force-device-scale-factor=<SCALE>
--virtual-time-budget=<BUDGET_MS>
--screenshot=<abs PNG path>
file:///<abs HTML path>
```

### 2. `tests/fixtures/sessions-demo.csv` (~40–60 hand-curated rows)

Synthetic sessions data to drive the demo screenshots. Replaces "snapshot real April 2026 spend" with stable, reproducible synthetic content so README screenshots don't churn with real-data drift.

- Columns: full sessions.csv header (label, session_date, session_id, first_timestamp, last_timestamp, cost_usd, …). Only `label`, `first_timestamp`, `cost_usd` are consumed by the plotters; remaining 17 columns can be empty/zero — `csv.DictReader` handles missing values gracefully.
- 2 labels: `chonkers`, `llamabox` (mirrors real two-host fleet for stacked-bar visual interest)
- Date range: covers Feb 2026 + March 2026 (so plot-compare's auto-PoP overlay has both windows populated when invoked with `--month 2026-03`)
- Per-day cost spread: 0–3 sessions/day across the range; per-session costs in $5–$300 range; chonkers dominates spend (matches real shape: heavy-usage host vs lighter)

### 3. `scripts/regen-screenshots.{sh,bat}` (~30 lines each)

Orchestrator. Runs:

```
python scripts/plot-trend.py    --month 2026-03 --csv tests/fixtures/sessions-demo.csv --inline-js --out reports/_trend-demo.html
python scripts/plot-compare.py  --month 2026-03 --csv tests/fixtures/sessions-demo.csv --inline-js --out reports/_compare-demo.html
python scripts/capture-screenshot.py reports/_trend-demo.html   screenshot-trend.png
python scripts/capture-screenshot.py reports/_compare-demo.html screenshot-compare.png
```

Then cleans up `reports/_*-demo.html` intermediates. `reports/` is already gitignored so demo HTML never gets committed.

`.bat` variant uses CRLF line endings (existing convention; cmd.exe parser needs CRLF on `:label` lines — see `feedback_write_tool_lf_windows.md` in user memory).

## File modifications

### `README.md`

- After "Trend across sessions" section: `![Aggregate cost trend across sessions](screenshot-trend.png)`
- After "Comparing two windows" section: `![Current vs prior window comparison](screenshot-compare.png)`
- In `## Files` section: add entries for `scripts/capture-screenshot.py`, `scripts/regen-screenshots.{sh,bat}`, `tests/fixtures/sessions-demo.csv`, `screenshot-trend.png`, `screenshot-compare.png`

### `../../install-skills.bat` and `../../install-skills.sh` (umbrella repo)

Both files have parallel `EXCLUDE_DIRS` / `EXCLUDE_FILES` lists applied to the root layout. Updates:

- Add `tests` to `EXCLUDE_DIRS` (so fixture CSV is dev-only)
- Add `capture-screenshot.py regen-screenshots.sh regen-screenshots.bat` to `EXCLUDE_FILES` (so Chrome wrapper + orchestrators are dev-only)

This change lives in the umbrella `skills-dev` repo, not the cost-estimator submodule.

## What does NOT change

- `SKILL.md` — screenshot regen is dev infra, not part of the skill's runtime behavior
- `screenshot.png` (existing per-session chart) — captured manually 2026-05-04, still accurate
- `scripts/run-tests.sh` — capture-screenshot is a shell tool, not unit-testable in isolation
- The existing handoff doc — keeps its historical-context role; superseded by this spec for the active design

## Watch-outs

These remain live concerns for implementation (verbatim from handoff):

1. **Empty-canvas screenshot** → bump `--virtual-time-budget` to 8000 or 10000 if Chart.js animation incomplete at snap time. Don't tune below 5000.
2. **`--disable-gpu` is required on Windows** — without it, stderr fills with GPU-init noise.
3. **`--inline-js` is non-negotiable** — without it the HTML references the Chart.js CDN, which the offline headless run can't fetch.
4. **Absolute PNG path** for `--screenshot=` — Chrome resolves relative paths against its own CWD (Chrome install dir on Windows).
5. **Window-size affects bar density** — 880×720 logical (1760×1440 @ 2x) is a starting point; bump to 1200×800 if charts look cramped.

## Out of scope

- CI-checked screenshot regression tests (would need `pillow` perceptual diffing — future work).
- Animated-GIF mode (would need `puppeteer-frame-recorder` or similar; requires Node.js).
- Regenerating `screenshot.png` (per-session chart) — left manual unless user asks.

## Smoke check

Acceptance: `regen-screenshots.{sh,bat}` produces two non-empty PNGs (>50KB each) at `screenshot-trend.png` and `screenshot-compare.png`, of dimensions 1760×1440, with visible bars (not blank canvas). Visual inspection in an image viewer confirms readability before committing.

---

## Spec lifecycle

This spec gets distilled into the plan header by `writing-plans` and deleted at that handoff. The handoff doc at `../2026-05-11-screenshot-automation-handoff.md` is also deleted once screenshots ship (its job is done). Lasting documentation goes into README.md updates and one-line docstrings in the new scripts — no doc-folder additions beyond cleanup.
