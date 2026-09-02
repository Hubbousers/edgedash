"""Load and validate project configuration from config.yaml at the repo root."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # noqa: F841
    sys.exit(
        "PyYAML is required: pip install pyyaml\n"
        "(needed to parse config.yaml — no alternative in the stdlib)"
    )

# Repo root is one level above this file's package directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

_DEFAULTS: dict[str, Any] = {
    "target_role": "Data Analyst",
    "target_city": "Bengaluru",
    "keywords": [],
    "my_skills": [],
    "experience_years": 0,
    "db_path": "edgedash.db",
    "min_fit_score": 50,
    "sources": ["arbeitnow"],
    "use_mock_fetcher": False,
    "llm_provider": "openrouter",
    "llm_model": "nvidia/nemotron-3-ultra-550b-a55b",
    "score_batch_size": 25,
    "llm_model_fallbacks": [
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-3-4b-it:free",
    ],
}


@dataclass
class Config:
    target_role: str
    target_city: str
    keywords: list[str]
    my_skills: list[str]
    experience_years: int
    db_path: str
    min_fit_score: int
    sources: list[str]
    use_mock_fetcher: bool
    llm_provider: str
    llm_model: str
    score_batch_size: int
    llm_model_fallbacks: list[str]

    # Convenience: resolve db_path relative to the repo root when it is not
    # an absolute path, so callers never have to think about working directory.
    @property
    def resolved_db_path(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else _REPO_ROOT / p


def load_config(path: Path = _CONFIG_PATH) -> Config:
    """Read *path* and return a validated Config.

    Raises FileNotFoundError with a human-readable message when the file is
    absent.  Falls back to _DEFAULTS for any field that is missing from the
    file so partial configs are still usable.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {path}\n"
            "Copy config.yaml.example to config.yaml and fill in your details."
        )

    with path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    merged = {**_DEFAULTS, **raw}

    return Config(
        target_role=str(merged["target_role"]),
        target_city=str(merged["target_city"]),
        keywords=list(merged["keywords"]),
        my_skills=list(merged["my_skills"]),
        experience_years=int(merged["experience_years"]),
        db_path=str(merged["db_path"]),
        min_fit_score=int(merged["min_fit_score"]),
        sources=list(merged["sources"]),
        use_mock_fetcher=bool(merged["use_mock_fetcher"]),
        llm_provider=str(merged["llm_provider"]),
        llm_model=str(merged["llm_model"]),
        score_batch_size=int(merged["score_batch_size"]),
        llm_model_fallbacks=list(merged["llm_model_fallbacks"]),
    )
