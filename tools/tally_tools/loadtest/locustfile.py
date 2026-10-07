"""PERF-1.1 under concurrency (P16.5): the dashboard summary at ≤ 3 s with 10 users.

Everything measured before this was single-session - `bench_analytics.py` is a median of five
sequential runs, which says what one query costs and nothing about what ten accountants opening
the dashboard at nine in the morning costs. PERF-VAL-2 asks for the concurrency to be recorded,
so it has to be a dimension of the measurement rather than an assumption.

    make loadtest                       # 10 users against a local backend
    make loadtest USERS=25 HOST=https://staging.example.in

What it measures: one **dashboard open**, as the browser performs it - the twelve summary calls
the Sales/Cash-flow landing view makes, issued together, timed as one user-visible event. A
per-request average would flatter us: the user waits for the slowest of the twelve, not the mean.
"""

import os
import random
from typing import Any

from locust import HttpUser, between, events, task

# The twelve calls one dashboard open makes, matching bench_analytics.DASHBOARD so the
# concurrent figures can be compared with the single-user ones.
# The API's own slugs are hyphenated (the MetricName enum in the path), even though the
# internal metric keys use underscores.
SUMMARY_METRICS = (
    "sales",
    "purchases",
    "expenses",
    "cash-flow",
    "cash-bank-position",
    "receivables",
    "payables",
    "product-difference",
)
RANKINGS = ("customers", "products")

EMAIL = os.environ.get("LOAD_EMAIL", "")
PASSWORD = os.environ.get("LOAD_PASSWORD", "")
PERIOD = {
    "from": os.environ.get("LOAD_FROM", "2025-04-01"),
    "to": os.environ.get("LOAD_TO", "2026-03-31"),
}


class Accountant(HttpUser):
    """One signed-in user who opens the dashboard, waits, and opens it again."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        if not EMAIL or not PASSWORD:
            raise RuntimeError("set LOAD_EMAIL and LOAD_PASSWORD (a real user on the target)")
        response = self.client.post(
            "/auth/login", json={"email": EMAIL, "password": PASSWORD}, name="/auth/login"
        )
        response.raise_for_status()
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        companies = self.client.get("/companies", headers=self.headers, name="/companies")
        companies.raise_for_status()
        body = companies.json()
        assert body, "the target has no companies; seed it with `make bench-data` first"
        self.company = body[0]["company_id"]

    @task
    def open_the_dashboard(self) -> None:
        """Timed as one event: the user waits for the whole view, not for an average call."""
        with self.client.get(
            f"/companies/{self.company}/analytics/sales",
            params=PERIOD,
            headers=self.headers,
            name="DASHBOARD (12 summary calls)",
            catch_response=True,
        ) as tracked:
            failed = []
            for metric in SUMMARY_METRICS[1:]:
                sub = self.client.get(
                    f"/companies/{self.company}/analytics/{metric}",
                    params=PERIOD,
                    headers=self.headers,
                    name=f"  /analytics/{metric}",
                )
                if sub.status_code != 200:
                    failed.append(f"{metric}: {sub.status_code}")
            for ranking in RANKINGS:
                sub = self.client.get(
                    f"/companies/{self.company}/analytics/{ranking}",
                    params=PERIOD | {"top_n": 10},
                    headers=self.headers,
                    name=f"  /analytics/{ranking}",
                )
                if sub.status_code != 200:
                    failed.append(f"{ranking}: {sub.status_code}")
            if failed:
                tracked.failure("; ".join(failed))
            elif tracked.status_code != 200:
                tracked.failure(f"sales: {tracked.status_code}")
            else:
                tracked.success()

    @task(1)
    def drill_into_a_month(self) -> None:
        """FR-DD-1: the drill-down is part of the same session's cost."""
        month = random.randint(1, 12)  # noqa: S311 - choosing a month to read, nothing secret
        year = 2025 if month >= 4 else 2026
        self.client.get(
            f"/companies/{self.company}/analytics/sales/drilldown",
            params={"from": f"{year}-{month:02d}-01", "to": f"{year}-{month:02d}-28", "limit": 50},
            headers=self.headers,
            name="/analytics/sales/drilldown",
        )


@events.quitting.add_listener
def _assert_perf_1_1(environment: Any, **_: Any) -> None:
    """Fail the run, not just report it: PERF-1.1 is a target, so the exit code should say.

    The 95th percentile, not the mean - the number that decides whether it felt slow.
    """
    dashboard = environment.stats.get("DASHBOARD (12 summary calls)", "GET")
    budget_ms = int(os.environ.get("LOAD_BUDGET_MS", "3000"))
    if dashboard.num_requests == 0:
        environment.process_exit_code = 1
        return
    p95 = dashboard.get_response_time_percentile(0.95)
    if dashboard.num_failures or p95 > budget_ms:
        environment.process_exit_code = 1
    else:
        environment.process_exit_code = 0
