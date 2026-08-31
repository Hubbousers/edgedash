"""Orchestrator — reads state, decides what to run, delegates to agents.

The Orchestrator never fetches data or scores listings itself.
It owns the cycle loop, the agent registry, and cycle_log writes.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from edgedash import storage
from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Console formatting helpers
# ---------------------------------------------------------------------------

_SEP = "─" * 60
_BOLD = "\033[1m"
_DIM  = "\033[2m"
_CYAN = "\033[96m"
_GRN  = "\033[92m"
_YLW  = "\033[93m"
_RED  = "\033[91m"
_RST  = "\033[0m"


def _h(text: str) -> str:
    """Bold cyan heading."""
    return f"{_BOLD}{_CYAN}{text}{_RST}"


def _status_color(status: str) -> str:
    colors = {"ok": _GRN, "failed": _RED, "skipped": _YLW}
    c = colors.get(status, "")
    return f"{_BOLD}{c}{status.upper()}{_RST}"


def _print_table(rows: list[tuple[str, str, str, str]]) -> None:
    """Print a fixed-width summary table from (agent, status, records, notes)."""
    col_w = [20, 8, 9, 0]
    header = (
        f"{'AGENT':<{col_w[0]}}  {'STATUS':<{col_w[1]}}  "
        f"{'RECORDS':>{col_w[2]}}  NOTES"
    )
    print(_h(header))
    print(_SEP)
    for agent, status, records, notes in rows:
        status_str = _status_color(status)
        # pad manually because ANSI codes inflate len()
        agent_col  = f"{agent:<{col_w[0]}}"
        rec_col    = f"{records:>{col_w[2]}}"
        print(f"{agent_col}  {status_str:<{col_w[1] + 10}}  {rec_col}  {notes or ''}")


# ---------------------------------------------------------------------------
# Placeholder agent factory
# ---------------------------------------------------------------------------

class _PlaceholderAgent:
    """Stand-in for agents not yet implemented."""

    def __init__(self, agent_name: str, reason: str) -> None:
        self.name = agent_name
        self._reason = reason

    def run(self, config: Config, db_path: str) -> AgentResult:
        msg = f"Not implemented yet — {self._reason}"
        print(f"  {_YLW}[SKIP]{_RST} {self.name}: {msg}")
        return AgentResult(
            agent=self.name,
            status="skipped",
            records_touched=0,
            notes=msg,
        )


# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------
# To swap MockFetcher for the real Fetcher: change line below and nothing else.

def _build_registry() -> list[Agent]:
    from edgedash.agents.mock_fetcher import MockFetcher  # noqa: PLC0415

    return [
        MockFetcher(),
        # --- PLACEHOLDER: replace with real Scorer when ready ---
        _PlaceholderAgent(
            "Scorer",
            "will score listings against profile using LLM or heuristic",
        ),
        # --- PLACEHOLDER: replace with real GapAnalyzer when ready ---
        _PlaceholderAgent(
            "GapAnalyzer",
            "will diff job skill requirements against config.my_skills",
        ),
    ]


# ---------------------------------------------------------------------------
# Core cycle
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decide(last_fetch: str | None, unscored: int) -> list[str]:
    """Return agent names to run this cycle, with a human-readable reason."""
    reasons: list[str] = []

    reasons.append(
        "Fetcher: always runs to check for new listings"
        + (f" (last fetch: {last_fetch})" if last_fetch else " (no previous fetch found)")
    )

    if unscored > 0:
        reasons.append(f"Scorer: {unscored} unscored listing(s) waiting")
    else:
        reasons.append("Scorer: 0 unscored listings — will still run as placeholder")

    reasons.append("GapAnalyzer: runs after every fetch to refresh skill-gap data")

    return reasons


def run_cycle(config: Config) -> None:
    db_path = str(config.resolved_db_path)
    cycle_start = _now_iso()

    # ── Banner ──────────────────────────────────────────────────────────────
    print()
    print(_SEP)
    print(_h("  EdgeDash — Cycle Start"))
    print(_SEP)
    print(f"  Started : {cycle_start}")
    print(f"  Profile : {config.target_role} · {config.target_city}")
    print(f"  Database: {db_path}")
    print()

    # ── 1. Init DB ──────────────────────────────────────────────────────────
    storage.init_db(db_path)

    # ── 2. Read state ───────────────────────────────────────────────────────
    last_fetch = storage.last_fetch_time(db_path)
    unscored   = storage.count_unscored(db_path)

    print(_h("  State"))
    print(_SEP)
    print(f"  Last fetch time : {last_fetch or 'none'}")
    print(f"  Unscored rows   : {unscored}")
    print()

    # ── 3. Plan ─────────────────────────────────────────────────────────────
    plan_reasons = _decide(last_fetch, unscored)
    print(_h("  Plan"))
    print(_SEP)
    for reason in plan_reasons:
        print(f"  • {reason}")
    print()

    # ── 4. Run agents ───────────────────────────────────────────────────────
    print(_h("  Running Agents"))
    print(_SEP)

    registry  = _build_registry()
    results:  list[AgentResult] = []

    for agent in registry:
        started_at  = _now_iso()
        print(f"  → {_BOLD}{agent.name}{_RST} …")

        try:
            result = agent.run(config, db_path)
        except Exception as exc:  # noqa: BLE001 — catch-and-log, then re-raise
            finished_at = _now_iso()
            storage.log_cycle(
                db_path,
                agent=agent.name,
                started_at=started_at,
                finished_at=finished_at,
                records_touched=0,
                status="failed",
                notes=str(exc),
            )
            print(f"  {_RED}[FAIL]{_RST} {agent.name}: {exc}", file=sys.stderr)
            raise

        finished_at = _now_iso()

        # ── 5. Log every agent run ──────────────────────────────────────────
        storage.log_cycle(
            db_path,
            agent=result.agent,
            started_at=started_at,
            finished_at=finished_at,
            records_touched=result.records_touched,
            status=result.status,
            notes=result.notes,
        )

        icon = _GRN + "✓" + _RST if result.status == "ok" else _YLW + "~" + _RST
        print(f"  {icon} {agent.name}: {result.notes or result.status}")
        results.append(result)

    # ── 6. Summary ──────────────────────────────────────────────────────────
    cycle_end = _now_iso()
    total_records = sum(r.records_touched for r in results)

    print()
    print(_h("  Cycle Summary"))
    print(_SEP)
    _print_table(
        [
            (r.agent, r.status, str(r.records_touched), r.notes or "")
            for r in results
        ]
    )
    print(_SEP)
    print(f"  Finished : {cycle_end}")
    print(f"  Total new records this cycle : {_BOLD}{total_records}{_RST}")
    print(_SEP)
    print()
