"""Shared contract for every EdgeDash agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from edgedash.config import Config


# Status values are a closed set — use Literal so type checkers catch typos.
Status = Literal["ok", "failed", "skipped"]


@dataclass
class AgentResult:
    agent: str
    status: Status
    records_touched: int
    notes: str | None = None


class Agent(Protocol):
    """Every agent must expose these two members.

    run() is the single entry point; it receives the full Config and the path
    to the database, executes its one goal, and returns an AgentResult.
    Storage access must go through edgedash.storage — never directly.
    """

    name: str

    def run(self, config: Config, db_path: str) -> AgentResult:
        ...
