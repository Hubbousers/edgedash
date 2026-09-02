"""Extraction step — the only part of the Scorer that calls a model.

Reads a job description and returns structured facts.
No scoring, no candidate profile, no weights.  The model reads a document.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from edgedash import storage
from edgedash.llm import LLMError, complete_json

# ---------------------------------------------------------------------------
# Extraction schema (steering rule 19 — facts only, no score field ever)
# ---------------------------------------------------------------------------

EXTRACTION_SCHEMA: dict[str, Any] = {
    "required": [
        "required_skills",
        "nice_to_have",
        "seniority",
        "years_required",
        "remote_ok",
    ],
    "properties": {
        "required_skills": {"type": "array"},
        "nice_to_have":    {"type": "array"},
        # seniority, years_required, remote_ok validated manually below
        # because they allow null or a constrained string set
    },
}

_VALID_SENIORITY = {"junior", "mid", "senior", "lead", "unknown"}

# ---------------------------------------------------------------------------
# Prompt  (model reads a document — no candidate, no profile, no score)
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are reading a job listing. Extract structured facts exactly as stated.

Rules:
- Report only what the listing explicitly says. Do not infer, guess, or fill gaps.
- If the listing does not state years of experience, set years_required to null.
- If the listing does not mention remote work, set remote_ok to null.
- If a skill appears as preferred, optional, or "nice to have", put it in \
nice_to_have only.
- If the listing gives no seniority signal, set seniority to "unknown".
- Do not evaluate any candidate. No candidate exists. You are reading a document.

Return a single JSON object with exactly these keys:
  required_skills  – list of skills the role requires (strings, lowercase)
  nice_to_have     – list of preferred or optional skills (strings, lowercase)
  seniority        – one of: "junior", "mid", "senior", "lead", "unknown"
  years_required   – integer years explicitly stated, or null
  remote_ok        – true if remote is explicitly permitted, false if \
explicitly office-only, null if not mentioned

Job listing:
---
{description}
---"""


# ---------------------------------------------------------------------------
# Post-validation for nullable / constrained fields
# ---------------------------------------------------------------------------

def _post_validate(data: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems, empty if data is clean."""
    problems: list[str] = []

    seniority = data.get("seniority")
    if seniority not in _VALID_SENIORITY:
        problems.append(
            f"seniority '{seniority}' is not one of {sorted(_VALID_SENIORITY)}"
        )

    yr = data.get("years_required")
    if yr is not None and not isinstance(yr, int):
        problems.append(f"years_required must be int or null, got {type(yr).__name__}")

    ro = data.get("remote_ok")
    if ro is not None and not isinstance(ro, bool):
        problems.append(f"remote_ok must be bool or null, got {type(ro).__name__}")

    for key in ("required_skills", "nice_to_have"):
        val = data.get(key, [])
        if not isinstance(val, list):
            problems.append(f"{key} must be a list")
        elif not all(isinstance(s, str) for s in val):
            problems.append(f"{key} must contain only strings")

    return problems


# ---------------------------------------------------------------------------
# Skill normalisation
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^\w\s\+\#\.\-]")


def _normalise_skill(skill: str) -> str:
    """Lowercase and strip punctuation noise while preserving C++, C#, .NET, multi-word."""
    cleaned = _STRIP_RE.sub("", skill.strip().lower())
    # collapse multiple spaces but keep single spaces (multi-word skills)
    return re.sub(r" {2,}", " ", cleaned).strip()


def _normalise_skills(skills: list[Any]) -> list[str]:
    return [_normalise_skill(str(s)) for s in skills if str(s).strip()]


# ---------------------------------------------------------------------------
# Description hash
# ---------------------------------------------------------------------------

def description_hash(text: str) -> str:
    """Stable 32-char SHA-256 hex digest of the description text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def extract(listing: dict[str, Any], config: Any, db_path: str) -> dict[str, Any]:
    """Extract structured facts from *listing* using the LLM.

    Cache-first: returns immediately if this description was seen before.
    Stores normalised result in extraction_cache keyed on description hash.
    Raises LLMError if the model fails after retries.
    """
    desc: str = listing.get("description") or ""
    if not desc.strip():
        return {
            "required_skills": [],
            "nice_to_have":    [],
            "seniority":       "unknown",
            "years_required":  None,
            "remote_ok":       None,
            "_cache_hit":      False,
            "_hash":           "",
        }

    # Strip HTML tags that Arbeitnow includes — model doesn't need markup
    clean_desc = re.sub(r"<[^>]+>", " ", desc)
    clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

    dhash = description_hash(clean_desc)

    # ── Cache check ─────────────────────────────────────────────────────────
    cached = storage.get_extraction_cache(db_path, dhash)
    if cached is not None:
        cached["_cache_hit"] = True
        cached["_hash"]      = dhash
        return cached

    # ── Model call ───────────────────────────────────────────────────────────
    prompt = _PROMPT_TEMPLATE.format(description=clean_desc[:4000])  # cap tokens

    raw = complete_json(prompt, EXTRACTION_SCHEMA, config=config, max_retries=1)
    raw.pop("_model_used", None)  # internal tracking key, not part of schema

    # ── Post-validation ──────────────────────────────────────────────────────
    problems = _post_validate(raw)
    if problems:
        raise LLMError(
            f"Extraction post-validation failed for listing "
            f"'{listing.get('title', '?')}': {problems}"
        )

    # ── Normalise skills ─────────────────────────────────────────────────────
    raw["required_skills"] = _normalise_skills(raw.get("required_skills", []))
    raw["nice_to_have"]    = _normalise_skills(raw.get("nice_to_have",    []))

    # Coerce years_required to int robustly (model sometimes returns "3")
    yr = raw.get("years_required")
    if yr is not None:
        try:
            raw["years_required"] = int(yr)
        except (ValueError, TypeError):
            raw["years_required"] = None

    # ── Store in cache ───────────────────────────────────────────────────────
    storage.set_extraction_cache(db_path, dhash, raw)

    raw["_cache_hit"] = False
    raw["_hash"]      = dhash
    return raw


# ---------------------------------------------------------------------------
# CLI check:  python -m edgedash.agents.extractor --check [--n 3]
# ---------------------------------------------------------------------------

def _run_check(n: int = 3) -> None:
    import json
    from pathlib import Path
    from dotenv import load_dotenv
    from edgedash.config import load_config

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    cfg     = load_config()
    db_path = str(cfg.resolved_db_path)

    from edgedash import storage
    storage.init_db(db_path)   # ensures extraction_cache table exists

    listings = storage.get_listings(db_path, limit=n)
    if not listings:
        print("No listings in DB — run:  python run_cycle.py")
        return

    for i, listing in enumerate(listings, 1):
        print(f"\n{'='*60}")
        print(f"  [{i}] {listing.get('title')} @ {listing.get('company')}")
        print(f"       source={listing.get('source')}  "
              f"desc_len={len(listing.get('description') or '')} chars")
        print(f"{'='*60}")
        try:
            result = extract(listing, cfg, db_path)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue

        cache_hit = result.pop("_cache_hit", False)
        dhash     = result.pop("_hash", "")
        tag = "CACHE HIT" if cache_hit else "model call"
        print(f"  {tag}  hash={dhash}")
        print(f"  seniority      : {result['seniority']}")
        print(f"  years_required : {result['years_required']}")
        print(f"  remote_ok      : {result['remote_ok']}")
        req = result["required_skills"]
        nth = result["nice_to_have"]
        print(f"  required_skills ({len(req)}): {req}")
        print(f"  nice_to_have    ({len(nth)}): {nth}")

    # verify cache: re-run first listing, must be a hit
    print(f"\n{'='*60}")
    print("  Cache verification — re-running listing 1…")
    r2 = extract(listings[0], cfg, db_path)
    hit = r2.pop("_cache_hit", False)
    status = "✓ PASS" if hit else "✗ FAIL — expected cache hit"
    print(f"  cache_hit: {hit}  {status}")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    n = 3
    if "--n" in args:
        idx = args.index("--n")
        try:
            n = int(args[idx + 1])
        except (IndexError, ValueError):
            pass
    if "--check" in args:
        _run_check(n)
    else:
        print("Usage: python -m edgedash.agents.extractor --check [--n <count>]")
        sys.exit(1)
