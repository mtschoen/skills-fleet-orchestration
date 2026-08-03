"""Shared root-resolution, date-bound, and stats-file helpers.

Extracted from analyze-month.py so stats_cache.py (and any future script)
can reuse the same logic without the spec-loader dance that analyze-month.py's
hyphenated filename forces. Keep this module dependency-free (stdlib only) so
it imports cleanly from anywhere.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def reports_directory() -> Path:
    """Stable output directory for CSVs, HTML charts, and saved reports.

    Lives OUTSIDE the installed skill tree so skill reinstalls can never
    delete generated data. Override with CLAUDE_COST_REPORTS_DIR.
    """
    override = os.environ.get("CLAUDE_COST_REPORTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "cost-estimator" / "reports"


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


def stats_file_for(projects_root):
    """Path to the stats-cache.json that sits next to a projects/ root.

    Claude Code writes stats-cache.json as a sibling of the projects/ dir
    (e.g. ~/.claude/projects -> ~/.claude/stats-cache.json), so it lives
    one level up from the root the cost scripts walk.
    """
    return Path(projects_root).parent / "stats-cache.json"


def month_bounds(month_string):
    """Parse YYYY-MM into [start, end) UTC bounds (end exclusive).

    TZ-AWARE (UTC) and END-EXCLUSIVE -- distinct from trend_data's
    inclusive_month_bounds() (naive, end-inclusive). Same concept,
    different contract; don't mix the two.
    """
    year, month = (int(part) for part in month_string.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    end = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
    return start, end


def date_bounds(start_string, end_string):
    """Parse YYYY-MM-DD start (inclusive) and end (inclusive) into UTC bounds.

    TZ-AWARE (UTC). The returned end is exclusive, matching the half-open
    convention used elsewhere: a session is in-range when
    start <= reference < end. Distinct from trend_data's
    inclusive_date_bounds() (naive, end-inclusive) -- same concept,
    different contract; don't mix the two.
    """
    start_year, start_month, start_day = (int(part) for part in start_string.split("-"))
    end_year, end_month, end_day = (int(part) for part in end_string.split("-"))
    start = datetime(start_year, start_month, start_day, tzinfo=timezone.utc)
    end_inclusive = datetime(end_year, end_month, end_day, tzinfo=timezone.utc)
    end_exclusive = end_inclusive + timedelta(days=1)
    return start, end_exclusive
