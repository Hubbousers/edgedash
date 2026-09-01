"""Read-only diagnostic tool.

Usage:
    python -m edgedash.diagnose

Reads from the existing database only.  No writes, no schema changes.
"""

from __future__ import annotations

import sys

from edgedash import storage
from edgedash.config import load_config

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

_SEP  = "─" * 60
_BOLD = "\033[1m"
_CYAN = "\033[96m"
_YLW  = "\033[93m"
_RED  = "\033[91m"
_GRN  = "\033[92m"
_RST  = "\033[0m"


def _h(text: str) -> str:
    return f"{_BOLD}{_CYAN}{text}{_RST}"


def _warn(text: str) -> str:
    return f"{_YLW}{text}{_RST}"


def _bad(text: str) -> str:
    return f"{_RED}{text}{_RST}"


def _good(text: str) -> str:
    return f"{_GRN}{text}{_RST}"


def _trunc(value: str | None, width: int) -> str:
    if value is None:
        return _bad("NULL".ljust(width))
    s = str(value)
    return (s[:width - 1] + "…") if len(s) > width else s.ljust(width)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _section_totals(db: str) -> int:
    """Print total listings and breakdown by source. Returns total count."""
    by_source = storage.count_by_source(db)
    total = sum(r["count"] for r in by_source)

    print(_h("  Listings in database"))
    print(_SEP)
    if not by_source:
        print("  (none — run python run_cycle.py first)")
        return 0

    print(f"  {'SOURCE':<20}  {'COUNT':>6}")
    print(f"  {'─'*20}  {'─'*6}")
    for row in by_source:
        print(f"  {row['source']:<20}  {row['count']:>6}")
    print(f"  {'─'*20}  {'─'*6}")
    print(f"  {'TOTAL':<20}  {_BOLD}{total:>6}{_RST}")
    return total


def _section_cross_dupes(db: str, total: int) -> None:
    """Print probable cross-source duplicates and a threshold assessment."""
    dupes = storage.cross_source_duplicates(db)
    dupe_count = len(dupes)

    print()
    print(_h("  Cross-source duplicates  (same title + company, different source)"))
    print(_SEP)

    if not dupes:
        print(_good("  None found."))
        return

    pct = (dupe_count / total * 100) if total else 0.0
    threshold_ok = pct < 10.0

    print(f"  {dupe_count} duplicate pair(s) — {pct:.1f}% of total listings")
    if threshold_ok:
        print(_good(f"  ✓ Under 10% threshold — acceptable, no action needed."))
    else:
        print(_warn(f"  ⚠ Exceeds 10% threshold — consider dedup strategy."))

    print()
    print(f"  {'TITLE':<35}  {'COMPANY':<20}  SOURCES")
    print(f"  {'─'*35}  {'─'*20}  {'─'*20}")
    for row in dupes[:20]:   # cap display at 20 rows
        title   = _trunc(row["title"],   35)
        company = _trunc(row["company"], 20)
        print(f"  {title}  {company}  {row['sources']}")

    if len(dupes) > 20:
        print(f"  … and {len(dupes) - 20} more")


def _section_recent(db: str) -> None:
    """Print the 5 most recently fetched listings."""
    rows = storage.recent_listings(db, n=5)

    print()
    print(_h("  5 most recent listings"))
    print(_SEP)

    if not rows:
        print("  (none)")
        return

    print(f"  {'FETCHED AT':<26}  {'SRC':<12}  {'TITLE':<30}  COMPANY")
    print(f"  {'─'*26}  {'─'*12}  {'─'*30}  {'─'*20}")
    for row in rows:
        ts      = _trunc(row["fetched_at"], 26)
        src     = _trunc(row["source"],     12)
        title   = _trunc(row["title"],      30)
        company = _trunc(row["company"],    20)
        print(f"  {ts}  {src}  {title}  {company}")


def _section_quality(db: str) -> None:
    """Print listings with NULL or empty url, title, or company."""
    issues = storage.quality_issues(db)

    print()
    print(_h("  Data quality issues  (NULL or empty url / title / company)"))
    print(_SEP)

    if not issues:
        print(_good("  None found — all rows have url, title, and company."))
        return

    print(_warn(f"  {len(issues)} listing(s) with missing fields:"))
    print()
    print(f"  {'ID':<34}  {'SRC':<12}  {'TITLE':<25}  {'COMPANY':<20}  URL")
    print(f"  {'─'*34}  {'─'*12}  {'─'*25}  {'─'*20}  {'─'*30}")
    for row in issues:
        rid     = _trunc(row["id"],      34)
        src     = _trunc(row["source"],  12)
        title   = _trunc(row["title"],   25)
        company = _trunc(row["company"], 20)
        url     = _trunc(row["url"],     30)
        print(f"  {rid}  {src}  {title}  {company}  {url}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    db     = str(config.resolved_db_path)

    print()
    print(_SEP)
    print(_h("  EdgeDash — Database Diagnostic"))
    print(_SEP)
    print(f"  Database: {db}")
    print()

    total = _section_totals(db)
    _section_cross_dupes(db, total)
    _section_recent(db)
    _section_quality(db)

    print()
    print(_SEP)
    print()


if __name__ == "__main__":
    main()
