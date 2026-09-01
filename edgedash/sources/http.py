"""Shared HTTP helper — the only place in the project that performs requests.

All network calls must go through get_json().  No bare requests.get anywhere
else in the codebase (steering rule 11).
"""

from __future__ import annotations

import time
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT: int = 10          # seconds
_MAX_RETRIES: int = 2
_BACKOFF_BASE: float = 1.0          # seconds; doubled on each retry
_USER_AGENT: str = (
    "EdgeDash/0.1 (autonomous career intelligence agent; "
    "https://github.com/your-org/edgedash)"
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class SourceError(Exception):
    """Raised when a source HTTP call fails after all retries."""


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> Any:
    """GET *url*, parse JSON, return the result.

    Retries up to _MAX_RETRIES times with exponential backoff on connection
    errors or non-2xx responses.  Raises SourceError if all attempts fail.
    """
    merged_headers = {"User-Agent": _USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 2):   # attempts: 1, 2, 3
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            last_exc = exc
            if attempt <= _MAX_RETRIES:
                wait = _BACKOFF_BASE * (2 ** (attempt - 1))   # 1s, 2s
                time.sleep(wait)

    raise SourceError(
        f"GET {url} failed after {_MAX_RETRIES + 1} attempts: {last_exc}"
    ) from last_exc
