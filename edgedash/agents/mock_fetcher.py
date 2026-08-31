"""MockFetcher — returns realistic fake listings without any network calls.

Designed to exercise the full storage path, including deduplication.
Four of the twelve listings have fixed URLs so their stable_id is identical
across every run; the remaining eight use a run-specific UUID in the URL so
they are always new on each run.  This makes dedup observable: run once → 12
new rows; run again → 8 new rows (the 4 fixed ones are ignored).
"""

from __future__ import annotations

import uuid
from datetime import date

from edgedash.agents.base import Agent, AgentResult
from edgedash.config import Config
from edgedash import storage


# ---------------------------------------------------------------------------
# Listing templates
# ---------------------------------------------------------------------------

# These four are FIXED across every run — same source + url → same stable_id.
_FIXED_LISTINGS: list[dict] = [
    {
        "title": "Data Analyst",
        "company": "Flipkart",
        "location": "Bengaluru",
        "url": "https://careers.flipkart.com/jobs/da-001",
        "source": "mock",
        "description": (
            "Own end-to-end reporting for the supply-chain vertical. "
            "Required: SQL, Python (pandas, numpy), Tableau. "
            "Nice-to-have: Spark, dbt."
        ),
        "posted_at": "2026-08-28",
    },
    {
        "title": "Senior Data Analyst",
        "company": "Swiggy",
        "location": "Bengaluru",
        "url": "https://careers.swiggy.com/jobs/sda-042",
        "source": "mock",
        "description": (
            "Drive growth analytics for the hyperlocal delivery platform. "
            "Required: advanced SQL, Python, Power BI. "
            "Experience with A/B testing frameworks essential."
        ),
        "posted_at": "2026-08-27",
    },
    {
        "title": "Business Intelligence Analyst",
        "company": "Razorpay",
        "location": "Bengaluru",
        "url": "https://razorpay.com/jobs/bia-017",
        "source": "mock",
        "description": (
            "Build self-serve BI for the payments and lending BUs. "
            "Required: SQL, Looker, dbt, Python. "
            "Strong stakeholder communication skills."
        ),
        "posted_at": "2026-08-26",
    },
    {
        "title": "Data Analyst — Growth",
        "company": "CRED",
        "location": "Bengaluru",
        "url": "https://careers.cred.club/jobs/dag-009",
        "source": "mock",
        "description": (
            "Analyse member behaviour and credit-card spend patterns. "
            "Required: SQL, Python, Excel, statistical modelling. "
            "Familiarity with Mixpanel or Amplitude a plus."
        ),
        "posted_at": "2026-08-25",
    },
]

# These eight use a run-specific UUID in the URL so they are always new.
_VARIABLE_TEMPLATES: list[dict] = [
    {
        "title": "Junior Data Analyst",
        "company": "Zepto",
        "location": "Bengaluru",
        "description": (
            "Support category and pricing teams with daily SQL reports. "
            "Required: SQL, Excel, basic Python. "
            "Good first role for 0-2 years experience."
        ),
        "posted_at": "2026-08-29",
    },
    {
        "title": "Data Analyst — Marketing",
        "company": "PhonePe",
        "location": "Bengaluru",
        "description": (
            "Measure campaign ROI across digital and offline channels. "
            "Required: SQL, Python, Google Analytics, Power BI."
        ),
        "posted_at": "2026-08-29",
    },
    {
        "title": "Product Data Analyst",
        "company": "Meesho",
        "location": "Bengaluru",
        "description": (
            "Partner with PMs on funnel analysis and feature rollout metrics. "
            "Required: SQL, Python, Amplitude, strong data storytelling."
        ),
        "posted_at": "2026-08-28",
    },
    {
        "title": "Data Analyst — Risk",
        "company": "BharatPe",
        "location": "Bengaluru",
        "description": (
            "Build risk scorecards and monitor portfolio health. "
            "Required: SQL, Python (scikit-learn), Excel, logistic regression basics."
        ),
        "posted_at": "2026-08-28",
    },
    {
        "title": "Analytics Engineer",
        "company": "Dunzo",
        "location": "Bengaluru",
        "description": (
            "Maintain the warehouse and build dbt models for the BI layer. "
            "Required: SQL, dbt, Python, Airflow. Snowflake experience preferred."
        ),
        "posted_at": "2026-08-27",
    },
    {
        "title": "Lead Data Analyst",
        "company": "Ola",
        "location": "Bengaluru",
        "description": (
            "Lead a team of 3 analysts covering driver-supply economics. "
            "Required: SQL, Python, Tableau, people management, stakeholder reporting."
        ),
        "posted_at": "2026-08-27",
    },
    {
        "title": "Data Analyst — Operations",
        "company": "BigBasket",
        "location": "Bengaluru",
        "description": (
            "Track SLA compliance and dark-store performance metrics. "
            "Required: SQL, Excel, Power BI. Python scripting a plus."
        ),
        "posted_at": "2026-08-26",
    },
    {
        "title": "Data Analyst (Contract)",
        "company": "Navi Technologies",
        "location": "Bengaluru",
        "description": (
            "6-month engagement to migrate legacy Excel dashboards to SQL + Looker. "
            "Required: SQL, Excel, Looker or Power BI."
        ),
        "posted_at": "2026-08-25",
    },
]


def _build_variable_listings(run_id: str) -> list[dict]:
    """Attach a unique URL per run so each variable listing gets a new stable_id."""
    out = []
    for i, tmpl in enumerate(_VARIABLE_TEMPLATES):
        row = dict(tmpl)
        row["url"] = f"https://mock.edgedash.local/{run_id}/{i}"
        row["source"] = "mock"
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class MockFetcher:
    name: str = "MockFetcher"

    def run(self, config: Config, db_path: str) -> AgentResult:
        run_id = uuid.uuid4().hex[:8]
        listings = _FIXED_LISTINGS + _build_variable_listings(run_id)

        new_count = storage.upsert_listings(db_path, listings)

        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=new_count,
            notes=(
                f"Fetched {len(listings)} listings "
                f"({new_count} new, {len(listings) - new_count} duplicates ignored). "
                f"run_id={run_id}"
            ),
        )
