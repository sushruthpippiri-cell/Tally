"""Repo-wide pytest hooks (CLAUDE.md "Testing and logs")."""

from collections.abc import Iterator

import pytest
import time_machine

from tally_contract.log import configure_logging
from tally_contract.testing import FIXED_NOW

pytest_plugins = ["pytester"]  # used to test the hooks below

configure_logging("test")

# Every test runs on this clock, never the real date (CLAUDE.md "Testing and logs"). It ticks,
# so durations still pass, but the date is always the same. A test about a particular moment
# travels there itself: `with time_machine.travel(<instant>, tick=False): ...`, or passes `now`.


@pytest.fixture(autouse=True)
def _fixed_clock() -> Iterator[None]:
    with time_machine.travel(FIXED_NOW, tick=True):
        yield


@pytest.fixture(autouse=True)
def _record_req_ids(request: pytest.FixtureRequest, record_property: object) -> None:
    """Write each `req` / `req_partial` marker ID into the JUnit XML for the phase report."""
    for name in ("req", "req_partial"):
        for marker in request.node.iter_markers(name):
            for req_id in marker.args:
                record_property(name, req_id)  # type: ignore[operator]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    """A skip must say why (e.g. "waiting on GATE-G23"); otherwise it fails."""
    outcome = yield
    rep = outcome.get_result()
    if rep.skipped and isinstance(rep.longrepr, tuple):
        reason = str(rep.longrepr[2]).removeprefix("Skipped").removeprefix(":").strip()
        if not reason:
            rep.outcome = "failed"
            rep.longrepr = "skipped without a reason: pass reason='waiting on GATE-Gxx' or similar"
