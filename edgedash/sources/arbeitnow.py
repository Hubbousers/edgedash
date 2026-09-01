"""Arbeitnow source — free public job board API, no key required.

API docs: https://www.arbeitnow.com/api/job-board-api
Terms:    link back to arbeitnow.com; do not abuse the free tier.
Rate:     1 request/second enforced below (steering rule 14).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from edgedash.config import Config
from edgedash.sources.base import Source, register
from edgedash.sources.http import get_json

_API_URL = "https://www.arbeitnow.com/api/job-board-api"
_PAGE_CAP = 5
_MIN_RESULTS_BEFORE_RELAX = 5
_RATE_LIMIT_SECS = 1.0   # max 1 req/sec (steering rule 14)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _parse_posted_at(created_at: int | str | None) -> str | None:
    """Convert a Unix timestamp or ISO string to an ISO-8601 date string."""
    if created_at is None:
        return None
    try:
        if isinstance(created_at, (int, float)):
            return datetime.fromtimestamp(
                int(created_at), tz=timezone.utc
            ).date().isoformat()
        # Already a string — normalise to date part only.
        return str(created_at)[:10] or None
    except (ValueError, OSError):
        return None


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source":      "arbeitnow",
        "external_id": raw.get("slug") or None,
        "title":       raw.get("title") or None,
        "company":     raw.get("company_name") or None,
        "location":    raw.get("location") or None,
        "url":         raw.get("url") or None,
        "description": raw.get("description") or None,
        "posted_at":   _parse_posted_at(raw.get("created_at")),
        "raw":         raw,
    }


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def _matches_keywords(row: dict[str, Any], keywords: list[str]) -> bool:
    """True if any keyword appears in title, description, tags, or job_types."""
    if not keywords:
        return True
    haystack = " ".join(
        filter(None, [
            row.get("title", ""),
            row.get("description", ""),
            " ".join(row.get("tags", []) or []),
            " ".join(row.get("job_types", []) or []),
        ])
    ).lower()
    return any(kw.lower() in haystack for kw in keywords)


def _matches_city(row: dict[str, Any], city: str) -> bool:
    location = (row.get("location") or "").lower()
    remote   = bool(row.get("remote", False))
    return city.lower() in location or remote


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

@register
class ArbeitnowSource(Source):
    name = "arbeitnow"

    def fetch(self, config: Config) -> list[dict]:
        keyword_matches: list[dict[str, Any]] = []

        for page in range(1, _PAGE_CAP + 1):
            data = get_json(_API_URL, params={"page": page})
            page_items: list[dict[str, Any]] = data.get("data", [])

            if not page_items:
                print(f"  [arbeitnow] page {page}: empty — stopping pagination")
                break

            # Keep only listings where at least one keyword matches.
            hits = [r for r in page_items if _matches_keywords(r, config.keywords)]
            keyword_matches.extend(hits)

            print(
                f"  [arbeitnow] page {page}: "
                f"{len(page_items)} raw, {len(hits)} keyword-matched"
            )

            # Stop paging when a full page yields no keyword hits — the feed
            # is ordered by recency so misses will only increase from here.
            if not hits:
                print(f"  [arbeitnow] no keyword hits on page {page} — stopping")
                break

            if page < _PAGE_CAP:
                time.sleep(_RATE_LIMIT_SECS)

        raw_count = len(keyword_matches)

        # ── Location filter ─────────────────────────────────────────────────
        city_filtered = [
            r for r in keyword_matches
            if _matches_city(r, config.target_city)
        ]

        if len(city_filtered) < _MIN_RESULTS_BEFORE_RELAX and keyword_matches:
            print(
                f"  [arbeitnow] only {len(city_filtered)} result(s) after "
                f"location filter '{config.target_city}' — relaxing to all "
                f"keyword-matched listings ({raw_count}) to avoid empty database"
            )
            final = keyword_matches
        else:
            final = city_filtered

        print(
            f"  [arbeitnow] {raw_count} keyword-matched → "
            f"{len(final)} after filters"
        )

        return [_normalise(r) for r in final]
