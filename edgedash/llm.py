"""Single door to any language model — steering rules 15-18.

Public API
----------
    complete_json(prompt, schema, *, config, max_retries=1) -> dict

Everything else in this file is private.  No other module may import an
LLM SDK or construct provider-specific requests.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when the model fails to return valid JSON after all retries."""


class LLMMissingKeyError(LLMError):
    """Raised when a required environment variable for a provider is absent."""


# ---------------------------------------------------------------------------
# Rate limiter  (steering rule 18: 1 req/s min, 15 req/min max)
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, min_gap_secs: float = 1.0, max_per_minute: int = 15) -> None:
        self._min_gap   = min_gap_secs
        self._max_pm    = max_per_minute
        self._history: deque[float] = deque()   # timestamps of recent calls
        self._last_call: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()

        # enforce minimum gap between calls
        gap = now - self._last_call
        if gap < self._min_gap:
            time.sleep(self._min_gap - gap)
            now = time.monotonic()

        # enforce rolling 60-second window cap
        cutoff = now - 60.0
        while self._history and self._history[0] < cutoff:
            self._history.popleft()

        if len(self._history) >= self._max_pm:
            oldest = self._history[0]
            sleep_for = (oldest + 60.0) - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()

        self._history.append(now)
        self._last_call = now


_limiter = _RateLimiter()


# ---------------------------------------------------------------------------
# JSON repair helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences and any leading/trailing prose."""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # No fence — find the first { or [ and take from there to the matching closer.
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        end   = text.rfind(end_char)
        if start != -1 and end > start:
            return text[start : end + 1]
    return text.strip()


def _parse_json(text: str) -> dict:
    cleaned = _strip_fences(text)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON parse failed: {exc}\nRaw text: {text[:300]}") from exc
    if not isinstance(result, dict):
        raise LLMError(f"Expected a JSON object, got {type(result).__name__}")
    return result


# ---------------------------------------------------------------------------
# Schema validation
#
# Schema format (subset of JSON Schema — enough for our extraction schemas):
#   {
#     "required": ["field1", "field2"],
#     "properties": {
#       "field1": {"type": "string"},
#       "field2": {"type": "array"},
#       ...
#     }
#   }
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string":  str,
    "number":  (int, float),
    "integer": int,
    "boolean": bool,
    "array":   list,
    "object":  dict,
    "null":    type(None),
}


def _validate(data: dict, schema: dict) -> None:
    """Raise LLMError with a human-readable message if data fails schema."""
    required: list[str] = schema.get("required", [])
    properties: dict    = schema.get("properties", {})

    missing = [k for k in required if k not in data]
    if missing:
        raise LLMError(f"Schema validation failed — missing keys: {missing}")

    errors: list[str] = []
    for key, prop in properties.items():
        if key not in data:
            continue
        expected_type = prop.get("type")
        if expected_type and expected_type in _TYPE_MAP:
            py_type = _TYPE_MAP[expected_type]
            if not isinstance(data[key], py_type):
                errors.append(
                    f"'{key}': expected {expected_type}, "
                    f"got {type(data[key]).__name__}"
                )
    if errors:
        raise LLMError("Schema validation failed — type errors: " + "; ".join(errors))


# ---------------------------------------------------------------------------
# Provider implementations
# Each callable: (prompt: str, model: str) -> str  (raw model text)
# ---------------------------------------------------------------------------

def _call_openrouter(prompt: str, model: str) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise LLMMissingKeyError(
            "OPENROUTER_API_KEY is not set.\n"
            "Add it to your .env file: OPENROUTER_API_KEY=sk-or-...\n"
            "Get a key at https://openrouter.ai/keys"
        )

    import requests  # already in requirements.txt

    headers = {
        "Authorization":  f"Bearer {key}",
        "Content-Type":   "application/json",
        "HTTP-Referer":   "https://github.com/your-org/edgedash",
        "X-Title":        "EdgeDash",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, 4):  # 3 attempts with backoff on 429
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=60,
        )
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"  [llm] 429 rate-limited — waiting {wait}s (attempt {attempt}/3)")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    raise LLMError("OpenRouter returned 429 after 3 attempts — quota exceeded")


def _call_gemini(prompt: str, model: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LLMMissingKeyError(
            "GEMINI_API_KEY is not set.\n"
            "Add it to your .env file: GEMINI_API_KEY=AIza...\n"
            "Get a key at https://aistudio.google.com/app/apikey"
        )

    import google.generativeai as genai  # google-generativeai in requirements

    genai.configure(api_key=key)
    gemini = genai.GenerativeModel(model)
    response = gemini.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json"
        ),
    )
    return response.text


def _call_ollama(prompt: str, model: str) -> str:
    """Local Ollama — no key required.  Assumes Ollama is running on localhost."""
    import requests

    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["response"]


# Registry: adding a new provider = one entry here, nothing else changes.
_PROVIDERS: dict[str, Any] = {
    "openrouter": _call_openrouter,
    "gemini":     _call_gemini,
    "ollama":     _call_ollama,
}


# Status codes that mean "this model can't serve you right now" — try next.
_FALLBACK_STATUS_CODES: frozenset[int] = frozenset({402, 404, 429, 500, 502, 503, 504})


def _is_quota_error(exc: Exception) -> bool:
    """True when the exception signals a billing/quota/availability failure."""
    import requests as _req
    if isinstance(exc, _req.exceptions.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        return code in _FALLBACK_STATUS_CODES
    return False


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def complete_json(
    prompt: str,
    schema: dict,
    *,
    config: Any,          # edgedash.config.Config — typed as Any to avoid
    max_retries: int = 1, # circular import; callers pass the real Config object
) -> dict:
    """Send *prompt* to the configured provider, validate against *schema*, return dict.

    Model selection
    ---------------
    Tries config.llm_model first.  On a 402/429/5xx response it moves through
    config.llm_model_fallbacks in order — loudly logging each switch.  Every
    other error (bad JSON, schema failure) triggers a same-model content retry
    up to max_retries times before moving to the next model.

    Raises LLMError if all models are exhausted.
    Missing key raises LLMMissingKeyError immediately — never falls back.
    """
    provider_name: str = config.llm_provider
    call_fn = _PROVIDERS.get(provider_name)
    if call_fn is None:
        raise LLMError(
            f"Unknown llm_provider '{provider_name}'. "
            f"Supported: {list(_PROVIDERS)}"
        )

    model_queue: list[str] = [config.llm_model] + list(
        getattr(config, "llm_model_fallbacks", [])
    )

    last_error: Exception | None = None

    for model in model_queue:
        last_content_error: LLMError | None = None

        for attempt in range(max_retries + 1):
            current_prompt = prompt
            if attempt > 0 and last_content_error is not None:
                current_prompt = (
                    f"{prompt}\n\n"
                    f"Your previous response failed validation with this error:\n"
                    f"{last_content_error}\n\n"
                    "Reply with valid JSON only. No prose. No markdown fences."
                )

            _limiter.wait()

            try:
                raw = call_fn(current_prompt, model)
                data = _parse_json(raw)
                _validate(data, schema)
                # Attach which model actually answered so callers can log it.
                data["_model_used"] = model
                return data

            except LLMMissingKeyError:
                raise  # config problem — never retryable, never falls back

            except Exception as exc:
                if _is_quota_error(exc):
                    # Billing/quota failure — no point retrying same model.
                    print(
                        f"  [llm] {model} unavailable "
                        f"({type(exc).__name__}) — trying next fallback"
                    )
                    last_error = exc
                    break  # move to next model in queue
                else:
                    last_content_error = (
                        exc if isinstance(exc, LLMError)
                        else LLMError(str(exc))
                    )
                    last_error = last_content_error
                    if attempt < max_retries:
                        print(
                            f"  [llm] {model} attempt {attempt + 1} "
                            f"failed ({last_content_error}) — retrying content"
                        )
        else:
            # Exhausted content retries without a quota error — model gave bad
            # output consistently; treat it as failed and try next.
            if last_content_error is not None:
                print(
                    f"  [llm] {model} failed after {max_retries + 1} "
                    f"content attempt(s) — trying next fallback"
                )

    raise LLMError(
        f"All models exhausted {model_queue}. Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# CLI check:  python -m edgedash.llm --check
# ---------------------------------------------------------------------------

def _run_check() -> None:
    from edgedash.config import load_config

    cfg = load_config()
    print(f"  provider  : {cfg.llm_provider}")
    print(f"  primary   : {cfg.llm_model}")
    print(f"  fallbacks : {cfg.llm_model_fallbacks or '(none)'}")
    print("  sending test prompt…")

    schema = {
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    result = complete_json(
        'Reply with {"answer": "ok"}',
        schema,
        config=cfg,
    )
    used = result.pop("_model_used", cfg.llm_model)
    print(f"  answered by : {used}")
    print(f"  response    : {result}")
    print("  ✓ LLM check passed")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        # Load .env before anything else — same pattern used at app startup.
        from pathlib import Path
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        _run_check()
    else:
        print("Usage: python -m edgedash.llm --check")
        sys.exit(1)
