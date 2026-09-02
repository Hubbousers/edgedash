# EdgeDash Project Steering

## Project

EdgeDash is an autonomous AI career intelligence agent. It runs as a scheduled
loop that fetches live job listings, scores them for fit against a user profile,
surfaces skill gaps, verifies its own output, and publishes a Streamlit dashboard.

## Architecture

```
Trigger (scheduled)
  -> Orchestrator
    -> Fetcher      (sub-agent)
    -> Scorer       (sub-agent)
    -> GapAnalyzer  (sub-agent)
  -> Verifier
  -> Storage
  -> Dashboard (read-only)
```

- The **Orchestrator** reads state and delegates work to sub-agents. It never
  fetches job data or scores listings directly.
- Each **sub-agent** has exactly one goal and one stop condition.
- The **Dashboard** is strictly read-only; it never writes to storage.

Do not deviate from this architecture without explaining the reason and getting
explicit confirmation.

## Hard Rules

1. **Python 3.11+. Standard library first.** Add a third-party dependency only
   when it genuinely saves real work. State the dependency name and the reason
   before adding it.

2. **All storage access goes through a single `storage` module.** That module
   exposes a thin interface (functions or a class). No other module may import
   `sqlite3` directly. The project will migrate from SQLite to hosted Postgres in
   week 4; that must be a one-file change.

3. **No hardcoded user-specific values.** Role, city, keywords, skills profile,
   and any other personal configuration live in `config` (e.g. `config.toml` or
   `config.py`). Code reads from config; it never embeds these values as
   literals.

4. **No secrets in code.** API keys, tokens, and credentials are loaded from
   environment variables in one place only (e.g. a `settings.py` or `env.py`
   module). Nothing secret is ever written to source files.

5. **Every agent run writes a row to `cycle_log`.** Required columns: agent
   name, start timestamp, records touched, pass/fail status, retry reason (null
   if none). This is mandatory, not optional.

6. **Fail loudly.** No bare `except: pass` and no silent swallowing of errors.
   If something goes wrong, raise or log with enough context to diagnose it.

7. **Type hints on every function signature.** Add docstrings only where the
   intent is not obvious from the function name and its parameter names.

8. **Keep files under ~150 lines.** Proactively split a module before it becomes
   a problem, not after.

## Network & Sources

9. **Every external source lives behind a `Source` class with a uniform
   interface.** The Fetcher never contains source-specific parsing logic.
   Adding a new source must never require editing the Fetcher.

10. **Every `Source` returns a list of normalised dicts with exactly these
    keys:** `source`, `external_id`, `title`, `company`, `location`, `url`,
    `description`, `posted_at`, `raw`. Missing values are `None` — never an
    empty string, never `"N/A"`.

11. **All network calls go through one shared helper** with a 10-second
    timeout (default), explicit retry (2 attempts, exponential backoff), and a
    `User-Agent` header. No bare `requests.get` anywhere else in the codebase.

12. **A source failing must never kill the cycle.** Catch failures per-source,
    log the failure to `cycle_log` with `status="failed"`, and continue to the
    next source. One dead job board must not stop the others.

13. **Secrets come from environment variables, loaded via a `.env` file that is
    gitignored.** Never a literal key in code, never a key in `config.yaml`. If
    a required key is missing, that source skips itself with a clear log line —
    it does not crash the cycle.

14. **Respect the source.** Rate-limit to at most 1 request per second per
    source, set a real `User-Agent`, and honour any documented page limits.

## Intelligence & Scoring

15. **All LLM calls go through `edgedash/llm.py` only.** That module exposes
    one function. The provider and model name come from config, never hardcoded.
    No other file imports an LLM SDK or makes direct LLM API calls.

16. **Use OpenRouter as the LLM provider.** The API key comes from
    `OPENROUTER_API_KEY` in the environment — never hardcoded, never in
    `config.yaml`. If the key is missing, raise a clear, actionable error. Never
    silently fall back to another provider. The OpenRouter base URL and
    authentication are centralised inside `llm.py`; no other module may know
    how to construct or authenticate an OpenRouter request.

17. **Keep provider and model separate in config:**
    ```yaml
    llm_provider: "openrouter"
    llm_model: "openai/gpt-oss-20b"   # change here only — never in code
    score_batch_size: 25
    ```
    Changing the model must require a config change only, not a code change.

18. **Rate-limit all OpenRouter calls inside `llm.py`:** default 1 request per
    second, max 15 per minute. The limiter applies to every call; callers do not
    manage it.

19. **The model extracts structured facts only — never scores or rankings.**
    All scoring arithmetic is deterministic Python in one function. The model
    never sees the scoring weights.

20. **Every model response is validated against an explicit schema before use.**
    A response that fails validation is retried once, then logged as a failure
    for that listing only — it must not crash the cycle or stop remaining
    listings. Never `json.loads` raw model text without a validation and repair
    path. When the selected model supports it, request structured JSON output via
    OpenRouter; do not rely on provider-specific behaviour alone.

21. **Scoring is idempotent.** Never re-score a listing that already has a
    score. Select only `WHERE fit_score IS NULL`. Cache extraction results keyed
    on a hash of the job description so the same text is never sent to the model
    twice.

22. **Every score carries a human-readable reason generated from the score
    components by our code** — never free text written by the model.

23. **Log the score distribution** (count, min, max, mean, spread) to
    `cycle_log` on every scoring run. A run where all scores fall within 10
    points of each other is a suspect run and must be logged as such.

24. **Cap listings scored per cycle at `score_batch_size`** (default 25) so a
    cost or rate-limit blowup is structurally impossible.

## Style

- Small, testable functions over large procedural blocks.
- Plain, readable Python over clever Python.
- When asked to build one module, build that module only — do not scaffold the
  whole application.
