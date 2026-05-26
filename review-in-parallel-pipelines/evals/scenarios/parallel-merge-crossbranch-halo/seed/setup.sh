#!/usr/bin/env bash
# Round-boundary HALO scenario. Three branches, each clean and correct in
# isolation (every per-branch diff passes review on its own; build + tests stay
# green after all three merge). The defect is a CROSS-BRANCH halo that no
# single-branch review can see by construction:
#
#   branch-a adds `slugify` in src/textutil.py and uses it.
#   branch-b INDEPENDENTLY adds an identical `slugify` inside src/search.py
#           (its author didn't know branch-a created textutil.slugify).
#
# After merging both, `main` has the same helper defined twice — duplicated
# logic that should be consolidated (search.py should import textutil.slugify).
# Only a round-boundary review that compares branches against each other, or
# inspects the integrated whole, surfaces it. branch-c is unrelated and clean.
#
# Run with cwd == the workspace root. Self-deletes at the end.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
git config user.email "eval-seed@example.com"
git config user.name "Eval Seed"
git config commit.gpgsign false

mkdir -p src tests reports

cat > pyproject.toml <<'EOF'
[project]
name = "directory-demo"
version = "0.3.0"

[tool.coverage.report]
fail_under = 80
show_missing = true
EOF

cat > src/__init__.py <<'EOF'
EOF

cat > src/users.py <<'EOF'
USERS = [{"name": "Ada Lovelace"}, {"name": "Alan Turing"}]


def all_users() -> list[dict]:
    return list(USERS)
EOF

cat > tests/test_users.py <<'EOF'
from src.users import all_users


def test_all_users():
    assert len(all_users()) == 2
EOF

cat > PLAN.md <<'EOF'
# Implementation Plan

## Phase 2 — DONE
User directory primitives landed on `main`.

## Phase 3 — three parallel tasks (this round)
Dispatched concurrently into isolated branches:

- **branch-a** — add `src/export.py` that exports users to a file whose name is
  a URL-safe slug of the user's name.
- **branch-b** — add `src/search.py` with a `search(query, users)` that matches
  users by a normalized form of their name.
- **branch-c** — add `src/pagination.py` with a `paginate(items, page, size)`
  helper.

## Phase 4, 5, 6 — queued
(blocked on phase 3 landing)
EOF

git add -A
git commit -qm "phase 2: user directory primitives"

# branch-a — export, introduces textutil.slugify (the canonical home).
git checkout -qb branch-a main
cat > src/textutil.py <<'EOF'
def slugify(value: str) -> str:
    """Lowercase, collapse whitespace to single hyphens."""
    return "-".join(value.lower().split())
EOF
cat > src/export.py <<'EOF'
from src.textutil import slugify


def export_filename(user: dict) -> str:
    return f"{slugify(user['name'])}.json"
EOF
cat > tests/test_export.py <<'EOF'
from src.export import export_filename


def test_export_filename():
    assert export_filename({"name": "Ada Lovelace"}) == "ada-lovelace.json"
EOF
git add -A
git commit -qm "branch-a: export filenames via textutil.slugify"

# branch-b — search, INDEPENDENTLY reimplements the same slugify locally.
git checkout -qb branch-b main
cat > src/search.py <<'EOF'
def slugify(value: str) -> str:
    """Lowercase, collapse whitespace to single hyphens."""
    return "-".join(value.lower().split())


def search(query: str, users: list[dict]) -> list[dict]:
    needle = slugify(query)
    return [u for u in users if slugify(u["name"]).startswith(needle)]
EOF
cat > tests/test_search.py <<'EOF'
from src.search import search
from src.users import all_users


def test_search_prefix():
    results = search("Ada", all_users())
    assert results == [{"name": "Ada Lovelace"}]
EOF
git add -A
git commit -qm "branch-b: name search with normalized matching"

# branch-c — pagination, unrelated and clean.
git checkout -qb branch-c main
cat > src/pagination.py <<'EOF'
def paginate(items: list, page: int, size: int) -> list:
    start = (page - 1) * size
    return items[start:start + size]
EOF
cat > tests/test_pagination.py <<'EOF'
from src.pagination import paginate


def test_paginate_second_page():
    assert paginate([1, 2, 3, 4, 5], page=2, size=2) == [3, 4]
EOF
git add -A
git commit -qm "branch-c: add pagination helper"

git checkout -q main

cat > reports/branch-a.md <<'EOF'
# branch-a report — export

Added `src/export.py::export_filename`, which builds a URL-safe filename from a
user's name using a new `src/textutil.py::slugify` helper.

- `pytest`: 2 passed.
- coverage: 100% on new code, total above the 80% gate.

Ready to merge.
EOF

cat > reports/branch-b.md <<'EOF'
# branch-b report — search

Added `src/search.py` with `search(query, users)` that matches users by a
normalized form of their name (lowercased, whitespace collapsed).

- `pytest`: 2 passed.
- coverage: 100% on new code, total above the 80% gate.

Ready to merge.
EOF

cat > reports/branch-c.md <<'EOF'
# branch-c report — pagination

Added `src/pagination.py::paginate(items, page, size)`. No changes to existing
modules.

- `pytest`: 2 passed.
- coverage: 100% on new code, total above the 80% gate.

Ready to merge.
EOF

rm -f setup.sh

exit 0
