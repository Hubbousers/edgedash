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

## Style

- Small, testable functions over large procedural blocks.
- Plain, readable Python over clever Python.
- When asked to build one module, build that module only — do not scaffold the
  whole application.
