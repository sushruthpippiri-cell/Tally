"""Repo-wide pytest hooks (CLAUDE.md "Testing and logs")."""

import pytest

from tally_contract.log import configure_logging

pytest_plugins = ["pytester"]  # used to test the hooks below

configure_logging("test")


@pytest.fixture(autouse=True)
def _record_req_ids(request: pytest.FixtureRequest, record_property: object) -> None:
    """Write each `req` marker ID into the JUnit XML so phase reports can list them."""
    for marker in request.node.iter_markers("req"):
        for req_id in marker.args:
            record_property("req", req_id)  # type: ignore[operator]


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
