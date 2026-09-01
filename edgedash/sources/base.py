"""Source ABC and registry.

A Source fetches raw job listings from one external provider and returns them
as normalised dicts.  The Fetcher agent never contains source-specific logic;
it iterates the registry and calls fetch() on each entry.

Registering a new source:

    from edgedash.sources.base import register
    from edgedash.config import Config

    @register
    class MySource:
        name = "mysource"

        def fetch(self, config: Config) -> list[dict]:
            ...

That decorator call is the only change needed to make the source visible to
the Fetcher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from edgedash.config import Config

# ---------------------------------------------------------------------------
# Normalised row keys (steering rule 10)
# ---------------------------------------------------------------------------

NORMALISED_KEYS: tuple[str, ...] = (
    "source",
    "external_id",
    "title",
    "company",
    "location",
    "url",
    "description",
    "posted_at",
    "raw",
)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class Source(ABC):
    name: ClassVar[str]

    @abstractmethod
    def fetch(self, config: Config) -> list[dict]:
        """Return a list of normalised dicts conforming to NORMALISED_KEYS.

        Missing values must be None — never empty string, never "N/A".
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SOURCES: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    """Class decorator that adds *cls* to the global SOURCES registry."""
    SOURCES[cls.name] = cls
    return cls
