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

## Style

- Small, testable functions over large procedural blocks.
- Plain, readable Python over clever Python.
- When asked to build one module, build that module only — do not scaffold the
  whole application.
