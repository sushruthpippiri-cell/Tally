"""PERF-1.1 under concurrency (P16.5): the home view, at <= 3 s, with 10 users.

**What is measured is what the product does.** The home view is FR-4.1's: sales, cash and bank
position, receivables, payables, last sync and reconciliation status, and Agent health. In the
frontend that is `HomePage.tsx` - four analytics figures plus `/sync/status` and `/agents` - and the
layout's one availability probe, seven requests in all. `tools/tests/test_loadtest_profile.py`
pins this list against those files, so it cannot drift again.

It drifted once. The first version of this harness (and `bench_analytics.DASHBOARD` before it)
timed a twelve-call set that included cash flow, expenses, purchases, rankings and
`product_difference`, none of which the home view requests. The 6.8 s it reported described a
page no user opens.

Two profiles, because they answer different questions:

* **realistic** (`LOAD_PROFILE=realistic`, the default): each user opens the home view, reads it
  for 5-15 s, then opens a section and reads that for 5-15 s. This is "10 users using the
  product" and is the PERF-1.1 figure.
* **stress** (`LOAD_PROFILE=stress`): no think time. Ten users hammering the home view back to
  back is a capacity test, not a use of the product, and is reported separately.

The default period is the financial year to date, which is what the home view opens on
(`frontend/src/lib/filters.ts`). `LOAD_FROM`/`LOAD_TO` override it for the three-year worst case.
"""

import os
import random
import time
from typing import Any

from locust import HttpUser, between, constant, events, task

# What HomePage.tsx requests, in the order it requests it. Pinned by
# tools/tests/test_loadtest_profile.py, which reads the .tsx.
HOME_ANALYTICS = ("sales", "cash-bank-position", "receivables", "payables")
HOME_OTHER = ("/sync/status", "/agents")
# CompanyLayout asks this on every company page to decide whether to list the nav item
# (FR-PAY-6). Cheap while gate G25 has not passed; real work on every page load once it does.
LAYOUT_PROBE = ("payment-behaviour",)

# A section a user opens after the home view. Rotated so no one section is favoured.
# Aging is left out: it needs a side and an as-of date, and a section that 422s would put
# failures in a figure that has none.
SECTIONS = ("sales", "purchases", "customers", "products", "expenses", "cash-flow", "stock")

# A template ("loadtest{n}@example.com") gives each simulated user their own account; a plain
# LOAD_EMAIL keeps the single-account behaviour `make loadtest` has always had.
EMAIL_TEMPLATE = os.environ.get("LOAD_EMAIL_TEMPLATE", "")
EMAIL = os.environ.get("LOAD_EMAIL", "")
_NEXT_USER = iter(range(10_000))
PASSWORD = os.environ.get("LOAD_PASSWORD", "")
PROFILE = os.environ.get("LOAD_PROFILE", "realistic")
PERIOD = {
    "from": os.environ.get("LOAD_FROM", "2025-04-01"),
    "to": os.environ.get("LOAD_TO", "2026-03-31"),
}
# Reading time between page views; 5-15 s is the owner's figure for realistic use.
THINK = (5, 15)
GROUP = "HOME VIEW"


class Accountant(HttpUser):
    """One signed-in user."""

    wait_time = constant(0) if PROFILE == "stress" else between(*THINK)

    def on_start(self) -> None:
        email = EMAIL_TEMPLATE.format(n=next(_NEXT_USER)) if EMAIL_TEMPLATE else EMAIL
        if not email or not PASSWORD:
            raise RuntimeError("set LOAD_EMAIL (or LOAD_EMAIL_TEMPLATE) and LOAD_PASSWORD")
        response = self.client.post(
            "/auth/login", json={"email": email, "password": PASSWORD}, name="/auth/login"
        )
        response.raise_for_status()
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        companies = self.client.get("/companies", headers=self.headers, name="/companies")
        companies.raise_for_status()
        body = companies.json()
        assert body, "the target has no companies; seed it with `make bench-data` first"
        self.company = body[0]["company_id"]

    def _get(self, path: str, **params: Any) -> bool:
        response = self.client.get(
            f"/companies/{self.company}{path}",
            params=params or None,
            headers=self.headers,
            name=f"  {path}",
        )
        return bool(response.status_code == 200)

    @task(4)
    def open_the_home_view(self) -> None:
        """One home-view open, timed as the user experiences it: all seven requests, as one event.

        Timed around the group and reported through a custom event. `catch_response` records the
        enclosing request's *own* duration, so wrapping one call and issuing the rest inside it
        reported the time of that one call under the name of the whole - the original bug here.
        """
        started = time.perf_counter()
        failed = [
            p
            for p in (*HOME_ANALYTICS, *LAYOUT_PROBE)
            if not self._get(f"/analytics/{p}", **PERIOD)
        ]
        failed += [p for p in HOME_OTHER if not self._get(p)]
        self.environment.events.request.fire(
            request_type="GROUP",
            name=GROUP,
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=Exception("; ".join(failed)) if failed else None,
            context={},
        )

    @task(1)
    def open_a_section(self) -> None:
        """A drill into one section, as a user does after reading the home view."""
        self._get(f"/analytics/{random.choice(SECTIONS)}", **PERIOD)  # noqa: S311 - not secret


@events.quitting.add_listener
def _assert_perf_1_1(environment: Any, **_: Any) -> None:
    """Fail the run, not just report it: PERF-1.1 is a target, so the exit code should say.

    The 95th percentile, not the mean - the number that decides whether it felt slow.
    """
    home = environment.stats.get(GROUP, "GROUP")
    budget_ms = int(os.environ.get("LOAD_BUDGET_MS", "3000"))
    if home.num_requests == 0:
        environment.process_exit_code = 1
        return
    p95 = home.get_response_time_percentile(0.95)
    environment.process_exit_code = 1 if home.num_failures or p95 > budget_ms else 0
