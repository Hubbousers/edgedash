# EdgeDash

EdgeDash is an autonomous career intelligence agent that runs on a schedule,
fetches live job listings from configured sources, scores each listing for fit
against your profile, identifies skill gaps between what the market demands and
what you currently have, verifies its own output for consistency, and publishes
the results to a Streamlit dashboard — all without manual intervention.

---

## Architecture

```
Trigger (scheduled)
    │
    ▼
Orchestrator
    │
    ├──► Fetcher       fetch raw listings from job sources
    ├──► Scorer        score each listing against your profile
    └──► GapAnalyzer   surface skills you are missing
    │
    ▼
Verifier               sanity-check outputs before they are persisted
    │
    ▼
Storage                single module; the only code that touches the database
    │
    ▼
Dashboard (read-only)  Streamlit UI; never writes to storage
```

The Orchestrator reads state and delegates. It never fetches or scores directly.
Each agent has one goal and one stop condition.

---

## Current status

### Week 1 — foundation (done)

- [x] `edgedash/config.py` — `Config` dataclass, loaded from `config.yaml`
- [x] `edgedash/storage.py` — isolated storage module; SQLite backend
- [x] `edgedash/agents/base.py` — `Agent` protocol and `AgentResult` dataclass
- [x] `edgedash/agents/mock_fetcher.py` — **temporary** mock; returns 12 hardcoded
      listings to prove the loop and deduplication work without network calls
- [x] `edgedash/orchestrator.py` — cycle loop with registry, state read, planning,
      per-agent `cycle_log` writes, and console summary
- [x] `run_cycle.py` — entry point

### Week 2 — real data (coming)

- [ ] Replace `MockFetcher` with `Fetcher` (live job board API or scraper)
- [ ] `Scorer` agent — LLM or heuristic fit scoring against your profile
- [ ] `GapAnalyzer` agent — diff job skill requirements against `config.my_skills`

### Week 3 — verification and dashboard (coming)

- [ ] `Verifier` — checks scores and gaps for consistency before storage write
- [ ] Streamlit dashboard — read-only view of listings, scores, and skill gaps

### Week 4 — production (coming)

- [ ] Migrate storage backend from SQLite to hosted Postgres (one-file change)
- [ ] Scheduled trigger (cron or cloud scheduler)
- [ ] Deployment

---

## Setup

**Python 3.11 or later is required.**

1. Clone the repo and create a virtual environment:

   ```
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   source .venv/bin/activate     # macOS / Linux
   ```

2. Install dependencies:

   ```
   pip install pyyaml
   ```

3. Copy and edit the config:

   ```
   copy config.yaml config.yaml   # it already exists; just open and edit it
   ```

   Fields to update in `config.yaml`:

   | Field | What to put |
   |---|---|
   | `target_role` | The job title you are targeting |
   | `target_city` | Your preferred city or metro area |
   | `keywords` | Extra search terms to inject into queries |
   | `my_skills` | Your current skills (used by GapAnalyzer) |
   | `experience_years` | Your total years of relevant experience |
   | `min_fit_score` | Dashboard filter threshold (0–100) |

   Secrets (API keys, tokens) go in environment variables only — never in
   `config.yaml`.

4. Run one cycle:

   ```
   python run_cycle.py
   ```

   The database file (`edgedash.db` by default) is created automatically on
   first run. Run the command a second time to see deduplication in action: the
   4 fixed mock listings are silently ignored; only genuinely new rows are
   counted.

---

## Design decisions

**Storage is isolated behind one module.**
When the project migrates from SQLite to hosted Postgres in week 4, only
`edgedash/storage.py` needs to change. No other module imports `sqlite3`, so
the swap cannot silently break anything elsewhere, and the interface contract
stays identical.

**Listing IDs are stable hashes of source + URL.**
`INSERT OR IGNORE` on the primary key is only useful if the same job always
produces the same ID. Deriving the ID from content that does not change between
runs (the job board source name and the canonical listing URL) makes
deduplication deterministic and free of any external ID dependency.

**The Orchestrator delegates instead of doing the work itself.**
Keeping fetch, score, and gap-analysis logic in separate agents with a single
`run()` entry point means each agent can be developed, tested, replaced, or
skipped independently. The Orchestrator only needs to know the `Agent` protocol,
so adding a new agent tomorrow is a one-line registry change with no other
modifications required.
