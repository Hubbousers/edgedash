"""Single point of contact for all database operations.

No other module may import sqlite3.  To swap SQLite for Postgres, change only
this file.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect(path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS listings (
        id          TEXT PRIMARY KEY,
        title       TEXT,
        company     TEXT,
        location    TEXT,
        url         TEXT,
        description TEXT,
        source      TEXT,
        posted_at   TEXT,
        fetched_at  TEXT,
        fit_score   INTEGER,
        fit_reason  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_gaps (
        skill     TEXT PRIMARY KEY,
        frequency INTEGER,
        last_seen TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cycle_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        agent           TEXT,
        started_at      TEXT,
        finished_at     TEXT,
        records_touched INTEGER,
        status          TEXT,
        notes           TEXT
    )
    """,
]


def init_db(path: str | Path) -> None:
    """Create all tables if they do not already exist."""
    with _connect(path) as conn:
        for statement in _DDL:
            conn.execute(statement)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def stable_id(source: str, url: str) -> str:
    """Return a stable SHA-256-based hex digest for a (source, url) pair.

    Using the first 16 bytes keeps the id short while collision probability
    remains negligible for career-scale data volumes.
    """
    key = f"{source}||{url}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:32]


def upsert_listings(path: str | Path, rows: list[dict[str, Any]]) -> int:
    """Insert rows that are genuinely new; skip duplicates.

    Each dict must contain at minimum: title, company, location, url,
    description, source, posted_at.  The id field is derived automatically
    from source + url if not provided.

    Returns the count of rows that were actually inserted (not ignored).
    """
    if not rows:
        return 0

    sql = """
        INSERT OR IGNORE INTO listings
            (id, title, company, location, url, description,
             source, posted_at, fetched_at)
        VALUES
            (:id, :title, :company, :location, :url, :description,
             :source, :posted_at, :fetched_at)
    """
    fetched_at = _now_iso()
    prepped: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        record.setdefault("id", stable_id(record["source"], record["url"]))
        record.setdefault("fetched_at", fetched_at)
        prepped.append(record)

    with _connect(path) as conn:
        before: int = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        conn.executemany(sql, prepped)
        after: int = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]

    return after - before


def count_unscored(path: str | Path) -> int:
    """Return the number of listings that have not yet been scored."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE fit_score IS NULL"
        ).fetchone()
    return row[0]


def last_fetch_time(path: str | Path) -> str | None:
    """Return the most recent fetched_at timestamp across all listings, or None."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT MAX(fetched_at) FROM listings"
        ).fetchone()
    return row[0]


def log_cycle(
    path: str | Path,
    agent: str,
    started_at: str,
    finished_at: str,
    records_touched: int,
    status: str,
    notes: str | None = None,
) -> None:
    """Write one row to cycle_log recording what an agent run did."""
    sql = """
        INSERT INTO cycle_log
            (agent, started_at, finished_at, records_touched, status, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    with _connect(path) as conn:
        conn.execute(
            sql,
            (agent, started_at, finished_at, records_touched, status, notes),
        )


def count_by_source(path: str | Path) -> list[dict[str, Any]]:
    """Return [{source, count}] ordered by count descending."""
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) AS count FROM listings GROUP BY source ORDER BY count DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def cross_source_duplicates(path: str | Path) -> list[dict[str, Any]]:
    """Return listings that share an identical (title, company) pair across
    different sources — probable duplicates fetched from multiple boards."""
    sql = """
        SELECT title, company, COUNT(DISTINCT source) AS source_count,
               GROUP_CONCAT(DISTINCT source) AS sources
        FROM   listings
        WHERE  title IS NOT NULL AND company IS NOT NULL
        GROUP  BY LOWER(title), LOWER(company)
        HAVING COUNT(DISTINCT source) > 1
        ORDER  BY source_count DESC, company
    """
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def recent_listings(path: str | Path, n: int = 5) -> list[dict[str, Any]]:
    """Return the *n* most recently fetched listings."""
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT source, title, company, url, fetched_at FROM listings "
            "ORDER BY fetched_at DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [dict(r) for r in rows]


def quality_issues(path: str | Path) -> list[dict[str, Any]]:
    """Return listings where url, title, or company is NULL or empty string."""
    sql = """
        SELECT id, source, title, company, url
        FROM   listings
        WHERE  url     IS NULL OR TRIM(url)     = ''
            OR title   IS NULL OR TRIM(title)   = ''
            OR company IS NULL OR TRIM(company) = ''
        ORDER  BY fetched_at DESC
    """
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_listings(
    path: str | Path,
    limit: int = 50,
    min_score: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch listings ordered by fit_score descending.

    When min_score is provided only listings at or above that threshold are
    returned.  fit_score IS NULL rows are excluded when min_score is set.
    """
    if min_score is not None:
        sql = """
            SELECT * FROM listings
            WHERE fit_score >= ?
            ORDER BY fit_score DESC
            LIMIT ?
        """
        params: tuple[Any, ...] = (min_score, limit)
    else:
        sql = "SELECT * FROM listings ORDER BY fit_score DESC LIMIT ?"
        params = (limit,)

    with _connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(r) for r in rows]
