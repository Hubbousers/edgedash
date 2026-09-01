"""Fetcher agent — collects listings from all enabled sources.

One goal: iterate enabled sources, gather normalised rows, write to storage.
Stop condition: all enabled sources have been attempted (success or failure).

Sources are isolated behind the Source ABC; this agent never contains
source-specific parsing logic (steering rule 9).
"""

from __future__ import annotations

from datetime import datetime, timezone

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
import edgedash.sources  # noqa: F401 — triggers @register decorators on all sources
from edgedash.sources.base import SOURCES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Fetcher:
    name: str = "Fetcher"

    def run(self, config: Config, db_path: str) -> AgentResult:
        note_parts: list[str] = []
        total_new:  int = 0

        for source_name in config.sources:
            cls = SOURCES.get(source_name)
            if cls is None:
                msg = f"unknown source '{source_name}' — not in registry, skipping"
                print(f"  [Fetcher] WARNING: {msg}")
                note_parts.append(f"{source_name}: SKIPPED ({msg})")
                storage.log_cycle(
                    db_path,
                    agent=f"Fetcher/{source_name}",
                    started_at=_now_iso(),
                    finished_at=_now_iso(),
                    records_touched=0,
                    status="failed",
                    notes=msg,
                )
                continue

            source = cls()
            started_at = _now_iso()

            try:
                rows = source.fetch(config)
            except Exception as exc:  # per steering rule 12 — catch per-source
                finished_at = _now_iso()
                msg = f"{type(exc).__name__}: {exc}"
                print(f"  [Fetcher] WARNING: source '{source_name}' failed — {msg}")
                storage.log_cycle(
                    db_path,
                    agent=f"Fetcher/{source_name}",
                    started_at=started_at,
                    finished_at=finished_at,
                    records_touched=0,
                    status="failed",
                    notes=msg,
                )
                note_parts.append(f"{source_name}: FAILED ({type(exc).__name__})")
                continue  # one dead source must never stop the others

            # Attach the stable id before upsert — reuse storage.stable_id so
            # there is exactly one id implementation in the project.
            for row in rows:
                row.setdefault(
                    "id",
                    storage.stable_id(row["source"], row["url"]),
                )

            new_count = storage.upsert_listings(db_path, rows)
            finished_at = _now_iso()
            total_new += new_count

            storage.log_cycle(
                db_path,
                agent=f"Fetcher/{source_name}",
                started_at=started_at,
                finished_at=finished_at,
                records_touched=new_count,
                status="ok",
                notes=f"{len(rows)} fetched, {new_count} new",
            )
            note_parts.append(f"{source_name}: {len(rows)} rows ({new_count} new)")

        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=total_new,
            notes=" | ".join(note_parts) if note_parts else "no sources configured",
        )
