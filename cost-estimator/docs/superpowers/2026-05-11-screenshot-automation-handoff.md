# Screenshot automation — session handoff

**Date written:** 2026-05-11
**Parent feature:** plot-compare PoP overlay (just shipped: `4e927b2..83bd839`)
**Also covers:** the still-deferred trend-graph screenshot (from the 2026-05-11 trend-graph delivery)
**Purpose:** distill what the next session needs to automate generating the two missing README screenshots (`screenshot-trend.png`, `screenshot-compare.png`) without re-deriving context.

---

## TL;DR

Two PNG screenshots are still pending for the cost-estimator README — one for plot-trend, one for plot-compare. Both were explicitly deferred at branch-finish so the user could capture them in a real browser run. Capturing them by hand is fine the first time, but the user is asking for automation so future visual updates don't require manual screenshotting.

The decision is **headless Chrome CLI** (zero deps, native on Windows/Linux/Mac) plus a thin Python wrapper. Playwright would be cleaner around Chart.js render-timing but adds a ~150MB browser bundle — too heavy for a skill that's currently stdlib-only.

The work is ~80 lines of script + ~30 lines of regen orchestrator + 2 README image links. Estimate: 30-60 min.

---

## Current state (post-Task 9 of plot-compare)

- `cost-estimator` HEAD: `83bd839` (plan removed). Working tree clean.
- skills-dev umbrella: bumped to `a980554`, pushed to Gitea + GitHub.
- `scripts/plot-trend.py` and `scripts/plot-compare.py` both produce HTML to `reports/<name>.html`.
- README references screenshot in `## Per-session cost graph` section only (`screenshot.png` — that one exists, sibling of plot-session.py's chart). The `## Trend across sessions` and `## Comparing two windows` sections lack the image embed.
- `--inline-js` works on both plotters → produces self-contained HTML that headless Chrome can render offline.

---

## What's missing

1. `screenshot-trend.png` — a PNG of `plot-trend.py --month 2026-04` (or whichever range looks most representative). Embed in README "Trend across sessions" section.
2. `screenshot-compare.png` — a PNG of `plot-compare.py --month 2026-04`. Embed in README "Comparing two windows" section.
3. A reproducible mechanism so when the chart styling changes, regenerating the PNGs is one command.

---

## Tool decision: headless Chrome CLI

### What we evaluated

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| `chrome.exe --headless --screenshot` | Zero new deps; native on every modern OS; one-liner; `--virtual-time-budget` solves Chart.js timing | Chrome path detection is OS-specific; no fine-grained "wait for canvas paint" callback | **Picked.** |
| Playwright (Python) | Robust render-timing (`page.wait_for_function`); cross-browser; modern API | Adds `pip install playwright` + ~150MB Chromium bundle; CI footprint | Overkill for one-off screenshot regen |
| Puppeteer | Same render-timing strength | Node.js dep in a Python-pure skill | Not a fit |
| `wkhtmltopdf` / `weasyprint` etc. | Older PDF-first tools | Chart.js JS execution support is patchy | Skip |

### Chrome paths (per OS)

- **Windows (chonkers):** `C:\Program Files\Google\Chrome\Application\chrome.exe` (verified 2026-05-11)
- **macOS:** `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- **Linux:** `/usr/bin/google-chrome` or `/usr/bin/chromium-browser`

A small detector in the script (try each, take first that exists) handles cross-platform without configuration.

### Chrome flags we need

```
chrome.exe \
  --headless \
  --disable-gpu \              # avoid GPU init noise on headless
  --hide-scrollbars \          # cosmetic, prevents stray scrollbar in screenshot
  --window-size=1280,720 \     # README-friendly aspect; tune if needed
  --virtual-time-budget=5000 \ # let Chart.js mount + animate (default animation is ~1s)
  --screenshot=<out.png> \
  file:///<absolute path to html>
```

The `--virtual-time-budget=5000` flag is the key Chart.js-specific bit: without it, the screenshot fires before `new Chart(...)` finishes rendering, producing an empty canvas. 5s is generous; 2-3s would also work.

---

## Recommended implementation

### Files to create

1. **`scripts/capture-screenshot.py`** (~60 lines)

   ```python
   """Render an HTML file to a PNG via headless Chrome.

   Inputs: input HTML path, output PNG path, optional window size.
   Detects Chrome via a short candidate list (Win/macOS/Linux paths).
   Uses --virtual-time-budget=5000 so Chart.js animations complete
   before the snapshot fires.

   Usage:
       python capture-screenshot.py <in.html> <out.png>
           [--width 1280] [--height 720] [--budget-ms 5000]
   """
   ```

   Body responsibilities:
   - argparse for in/out + optional flags
   - locate Chrome via a `CHROME_CANDIDATES` list (env-var override `CHROME_PATH` first)
   - convert input path to `file:///` URL
   - subprocess.run the chrome command with stdout/stderr captured
   - non-zero exit → print stderr, sys.exit

2. **`scripts/regen-screenshots.{sh,bat}`** (~30 lines each)

   Orchestrator that:
   - ensures sessions.csv covers the demo range (run analyze-month if not)
   - runs plot-trend with `--inline-js --out reports/_trend-demo.html`
   - runs plot-compare with `--inline-js --out reports/_compare-demo.html`
   - runs capture-screenshot on each, writing to `screenshot-trend.png` and `screenshot-compare.png` at repo root
   - cleans up the `_*-demo.html` intermediates

   (.bat needs CRLF per cmd.exe — same convention as `run-tests.bat`.)

3. **No new test file needed** — capture-screenshot is a shell tool, not unit-testable in isolation. Smoke is "regen-screenshots produced two non-empty PNGs of expected dimensions". The regen script can echo `file <path>` to confirm.

### Files to modify

1. **`README.md`**:
   - After `## Trend across sessions` paragraph, add `![Aggregate cost trend across sessions](screenshot-trend.png)` (parallel to how `## Per-session cost graph` embeds `screenshot.png`).
   - After `## Comparing two windows` paragraph, add `![Current vs prior window comparison](screenshot-compare.png)`.
   - In `## Files` section, add entries for `scripts/capture-screenshot.py`, `scripts/regen-screenshots.{sh,bat}`, `screenshot-trend.png`, `screenshot-compare.png`.

2. **`SKILL.md`**: No change. The screenshot regen is dev-only infra, not part of the skill's runtime behavior.

3. **`.gitignore`**: confirm `reports/` is still excluded; the new screenshot PNGs sit at repo root (committed), not in `reports/` (gitignored).

---

## Stable-data question

The screenshots will show whatever totals are in the user's `sessions.csv` at regen time. Two approaches:

### Option A: Snapshot real data (recommended)

Just run regen with the user's actual data. The screenshot shows real April 2026 spend ($3703 chonkers, $79 March prior). When the data ages out and looks dated, regenerate from a more recent range. Trade-off: screenshots in the repo will become "snapshot from May 2026" forever — that's fine for a README; people don't expect README screenshots to be live.

### Option B: Synthetic fixture

Maintain a `tests/fixtures/sessions-demo.csv` (~20 hand-curated rows) and use it for the regen. Screenshots stay stable across regens; downside is fixture maintenance + the chart no longer reflects "what your actual data will look like."

**Recommendation: A.** The plot-session.py screenshot (the existing one, `screenshot.png`) was captured from real data; same convention here.

---

## Concrete step-by-step for next session

1. **Verify Chrome is reachable.**
   ```bash
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --version
   # expect: "Google Chrome 1XX.0.XXXX.XXX"
   ```
   If on a different OS, find the path and either set `CHROME_PATH` env var or update `CHROME_CANDIDATES` in the script.

2. **Write `scripts/capture-screenshot.py`** per the contract above. Smoke it manually on an existing HTML:
   ```bash
   python scripts/capture-screenshot.py reports/compare-2026-04.html /tmp/test.png
   file /tmp/test.png  # expect: "PNG image data, 1280 x 720, 8-bit/color RGB"
   ```

3. **Write `scripts/regen-screenshots.{sh,bat}`** that runs both plotters with `--inline-js` and snapshots both. Test:
   ```bash
   bash scripts/regen-screenshots.sh
   ls -la screenshot-*.png  # expect 2 files, each >50KB
   ```

4. **Visually inspect** the produced PNGs. Open them in an image viewer. Confirm:
   - Bars are visible (not empty canvas — that's the timing-budget failure mode)
   - Labels and legend are readable
   - Aspect ratio looks OK for README embedding (1280x720 is a starting point; may need adjustment)

5. **Embed in README.md**:
   ```markdown
   ![Aggregate cost trend across sessions](screenshot-trend.png)
   ```
   ```markdown
   ![Current vs prior window comparison](screenshot-compare.png)
   ```
   And add the 4 new file entries to `## Files`.

6. **Commit** as a single feature:
   ```bash
   git add scripts/capture-screenshot.py scripts/regen-screenshots.sh scripts/regen-screenshots.bat \
           screenshot-trend.png screenshot-compare.png README.md
   git commit -m "scripts: automate README screenshot regeneration via headless Chrome

   Adds scripts/capture-screenshot.py (60-line Chrome wrapper with
   --virtual-time-budget=5000 so Chart.js renders before snap) and
   scripts/regen-screenshots.{sh,bat} that orchestrates plot-trend +
   plot-compare HTML production + capture into two PNGs at repo root.
   Embeds both screenshots in the README, closing the two screenshot
   placeholders deferred from the trend-graph and plot-compare ships.

   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
   ```

7. **Bump umbrella pointer** and push:
   ```bash
   cd C:/Users/mtsch/skills-dev
   git add cost-estimator
   git commit -m "bump: cost-estimator -> $(git -C cost-estimator rev-parse --short HEAD) (README screenshots + capture automation)"
   cmd.exe /c scripts\\push-all.bat
   ```

8. **Delete this handoff doc** after the screenshots ship:
   ```bash
   cd C:/Users/mtsch/skills-dev/cost-estimator
   git rm docs/superpowers/2026-05-11-screenshot-automation-handoff.md
   git commit -m "docs: remove screenshot-automation handoff after ship"
   ```
   Then bump pointer + push again (or fold both commits with `git rebase -i HEAD~2` before bumping).

---

## Watch-outs

1. **Empty-canvas screenshot.** If the PNG comes back blank or with axis labels but no bars, the timing budget wasn't enough — bump `--virtual-time-budget` to 8000 or 10000ms. Don't waste time tuning below 5000; Chart.js animation defaults are slow.

2. **--disable-gpu necessary on Windows.** Without it, headless Chrome on Windows tries to init GPU and prints noise to stderr; with it, the snap is clean.

3. **Inline-js is non-negotiable.** Without `--inline-js`, the HTML references `https://cdn.jsdelivr.net/npm/chart.js@4`, which the headless run needs network for. With `--inline-js`, Chart.js is embedded — works offline, no flakiness.

4. **PNG file paths must be absolute.** Chrome's `--screenshot=` interprets relative paths against its own CWD (which is the Chrome install dir on Windows, where users don't have write permission). Always pass an absolute path.

5. **Window size affects bar density.** 1280x720 is a reasonable default for README readability. If the chart looks cramped (too many buckets), bump to 1600x900. The README image rendering scales it down anyway.

6. **Cross-machine reproducibility.** `regen-screenshots.sh` on llamabox vs chonkers will pull different `sessions.csv` data — fine, but the screenshot you commit should be from whichever host is your "demo data" host (probably chonkers, where the heavy usage is).

7. **Don't commit the intermediate `_trend-demo.html` / `_compare-demo.html`.** They're 3-4KB each and get regenerated every run. Delete them at the end of regen-screenshots, or add to .gitignore. (The `reports/` dir is already gitignored, so output there is fine; the issue is only if the script writes the demo HTML somewhere else.)

---

## What this enables, beyond the immediate screenshots

If you find yourself wanting CI-checked screenshot regression tests (e.g., "did a Chart.js version bump silently change the chart look?"), the `capture-screenshot.py` script is the right foundation. Combine with `image-diff` or `pillow`-based perceptual diffing and you have a regression test. Out of scope for now — the README screenshots are the immediate win.

If you want a `--gif` mode (animated chart trajectory), that's a bigger project — Chart.js doesn't render to animated images natively. `puppeteer-frame-recorder` is the typical path; would need Node.js. Not pursuing.

---

## Don't-touch list

- **The existing `screenshot.png`** (per-session chart) was captured by hand on 2026-05-04. Don't regenerate it as part of this work unless the user asks; it's still accurate.
- **Plan files** for trend-graph and plot-compare are both deleted (per branch-finish convention). Don't try to revive them for this handoff.
- **`scripts/run-tests.sh`** doesn't need to know about the screenshot scripts — they're not unit-testable in isolation.

---

## Open questions for the user (if any come up)

1. **Default window size for screenshots:** 1280x720 vs 1600x900 vs something else? Choose by eye after first regen.
2. **Whether to lock the screenshot to a specific date range** (e.g., always `--month 2026-04`) or always "current latest month at regen time"? Former is reproducible; latter is more representative of current usage. I'd lean **former** since regens will be infrequent.
3. **Whether to commit the screenshot regen script as part of the skill install** or treat it as dev-only. `install-skills.{sh,bat}` already excludes some dev-only paths for the root layout; `scripts/regen-screenshots.*` could be added to that exclude list. Worth checking the current exclude list in `install-skills.bat` before deciding.

---

End of handoff. Pick up in a fresh session. ~30-60 min total.
