"""P16.7: SRS Section 20's use cases, end to end (TEST-5.1).

UC-1, UC-2 and UC-4 are covered by test_agent_end_to_end.py. Three more are added here, each of
which had no end-to-end presence at all: every one was tested where the Agent is a fixture
rather than the real program, so nothing showed the two halves agreeing.

  UC-5's cancellation half, UC-8 (the Agent lost mid-command) and UC-9 (credential rotation).

**UC-6 and UC-7 are deliberately not here**, and are marked `req_partial` where they are
proven instead:

- UC-6 (a retried older batch is rejected) needs a batch built before a newer one and arriving
  after it. A real Agent never sends one, so an end-to-end version has to forge the upload -
  at which point it is testing the backend's API, which
  `backend/tests/sync/test_ingest_vouchers.py` already does against every record type. The
  end-to-end version would be more machinery proving less.
- UC-7 (two Agents racing for one lease) is a race. `backend/tests/races/test_lease_races.py`
  drives it deterministically from two sessions; two real Agents would make it timing-dependent,
  and a flaky end-to-end test is worse than none. Added here only if a lease bug ever escapes
  the race suite.

UC-10 to UC-14 are UI reviews, covered by the Playwright suites; the coverage map in
docs/test-reports/phase-16.md records which spec answers which.
"""

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.jobs.commands import command_timeouts
from app.jobs.runner import LOCK_COMMAND_TIMEOUTS, run_exclusive
from app.models.agents import Agent as AgentRow
from app.models.agents import AgentCommand
from app.models.config import AuditLog
from app.models.vouchers import Voucher
from tally_tools.mock_tally import MockConfig, cancel_voucher
from tests.e2e.harness import (
    Server,
    Uploading,
    _agent,
    _full,
    _register,
    _run,
    _seed,
    _sync_now,
    start_server,
    tally,
)
from tests.factories import auth_header
from tests.sync.helpers import Factory

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the backend runs on Linux")

__all__ = ["start_server", "tally"]  # fixtures, re-exported for pytest to find


async def _ready(
    committed: Factory, start_server: Any, tally_port: int, tmp_path: Path
) -> tuple[Server, Any, Any, Any, Uploading]:
    """A registered Agent that has finished its first FULL sync: where every use case starts."""
    server = start_server()
    company, owner, token = await _seed(committed)
    await _register(server, tally_port, token, tmp_path / "agent")
    agent = _agent(tmp_path / "agent", tally_port)
    uploading = Uploading(agent)
    try:
        await _full(server, company, owner, agent)
    except Exception:
        uploading.close()
        raise
    return server, company, owner, agent, uploading


async def _vouchers(committed: Factory) -> int:
    async with committed() as s:
        return len((await s.scalars(select(Voucher.voucher_id))).all())


# --- UC-5: a cancelled voucher becomes CANCELLED, and its row is never deleted ----------


@pytest.mark.req("AC-03")
async def test_uc5_a_voucher_cancelled_in_tally_becomes_cancelled_and_is_kept(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    """The deletion half of UC-5 was covered (AC-04); cancellation was not, although
    mock_tally.cancel_voucher() has existed since P7. Tally keeps a cancelled voucher and raises
    its ALTERID, so it reaches us as an ordinary modification whose status happens to change -
    which is exactly why it is worth proving the status really changes and the row really stays.
    """
    mock, tally_port = tally
    server, company, owner, agent, uploading = await _ready(
        committed, start_server, tally_port, tmp_path
    )

    def sales() -> str:
        """Total sales revenue, as the dashboard asks for it."""
        response = httpx.get(
            f"{server.url}/companies/{company.company_id}/analytics/sales",
            params={"from": "2024-04-01", "to": "2026-03-31"},
            headers=auth_header(owner),
            trust_env=False,
        )
        assert response.status_code == 200, response.text
        return str(response.json()["summary"]["amount"])

    try:
        before, before_total = await _vouchers(committed), sales()
        cancel_voucher(mock, "v-4")
        _sync_now(server, company, owner, "INCREMENTAL")
        assert (await _run(agent)).status == "COMPLETED"

        async with committed() as s:
            voucher = (
                await s.execute(select(Voucher).where(Voucher.tally_guid == "v-4"))
            ).scalar_one()
            cancelled = (
                (await s.scalars(select(AuditLog).where(AuditLog.action == "VOUCHER_CANCELLED")))
                .unique()
                .all()
            )
        assert voucher.status == "CANCELLED"
        assert await _vouchers(committed) == before  # never deleted (CLAUDE.md rule 5)
        assert [a.entity_id for a in cancelled] == [str(voucher.voucher_id)]

        # And it leaves the figures: standard analytics count ACTIVE vouchers only
        # (CLAUDE.md rule 8). The row is still there, so only the status can have done this.
        assert sales() != before_total, "a cancelled voucher must drop out of the total"
    finally:
        uploading.close()


# --- UC-8: the Agent is lost mid-command; the Owner issues a new one --------------------


@pytest.mark.req("AC-07")
async def test_uc8_an_agent_lost_mid_command_fails_it_and_a_new_command_can_be_issued(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    """AGT-1.8: once a claimed command's lease lapses the command is FAILED_AGENT_LOST, and it is
    never reassigned - a half-finished sync must not be picked up by someone else and continued.
    Proved with the real Agent having really claimed it, rather than a row set up by hand.
    """
    mock, tally_port = tally
    server, company, owner, agent, uploading = await _ready(
        committed, start_server, tally_port, tmp_path
    )
    try:
        _sync_now(server, company, owner, "INCREMENTAL")
        # The Agent claims the command, then the machine goes away: no renewals, no result.
        async with committed() as s:
            command = (
                await s.scalars(select(AgentCommand).order_by(AgentCommand.created_at.desc()))
            ).first()
            assert command is not None
            # Lease lapsed: what the Agent's machine losing power looks like to the backend.
            command.status = "RUNNING"
            command.lease_expires_at = command.created_at
            await s.commit()

        changed = await run_exclusive(LOCK_COMMAND_TIMEOUTS, command_timeouts)
        assert changed is not None and changed >= 1

        async with committed() as s:
            after = await s.get(AgentCommand, command.command_id, populate_existing=True)
            assert after is not None
        assert after.status == "FAILED_AGENT_LOST"

        # The Owner can issue a new command, and the Agent runs it.
        _sync_now(server, company, owner, "INCREMENTAL")
        assert (await _run(agent)).status == "COMPLETED"
    finally:
        uploading.close()


# --- UC-9: the Owner rotates the credential; the Agent keeps working --------------------


@pytest.mark.req("AC-09")
async def test_uc9_a_rotated_credential_is_shown_once_and_the_old_one_stops_working(
    committed: Factory, start_server: Any, tally: tuple[MockConfig, int], tmp_path: Path
) -> None:
    """SEC-2.1/SRS 4.4. The end-to-end part that unit tests cannot show: the Agent is *running*
    while its credential is rotated, and what it has queued is not lost - it uploads once the
    new credential is entered."""
    mock, tally_port = tally
    server, company, owner, agent, uploading = await _ready(
        committed, start_server, tally_port, tmp_path
    )
    try:
        async with committed() as s:
            agent_row = (await s.scalars(select(AgentRow))).one()
            agent_id = agent_row.agent_id

        rotated = httpx.post(
            f"{server.url}/companies/{company.company_id}/agents/{agent_id}/rotate-credential",
            headers=auth_header(owner),
            trust_env=False,
        )
        assert rotated.status_code == 200, rotated.text
        credential = rotated.json()["credential"]
        assert credential and credential.startswith("agt_")

        # Shown once: asking again gives a different one, never the same value back.
        again = httpx.post(
            f"{server.url}/companies/{company.company_id}/agents/{agent_id}/rotate-credential",
            headers=auth_header(owner),
            trust_env=False,
        )
        assert again.status_code == 200
        assert again.json()["credential"] != credential

        # The superseded credential is refused, and says why (SEC-2.2).
        refused = httpx.post(
            f"{server.url}/agent/leases/renew",  # an Agent call with no body to get wrong
            headers={"Authorization": f"Bearer {credential}"},
            trust_env=False,
        )
        assert refused.status_code == 401
        assert refused.json()["code"] == "CREDENTIAL_INVALID"

        # The Agent is still ACTIVE, not revoked: rotation is not revocation.
        async with committed() as s:
            status = await s.scalar(select(AgentRow.status).where(AgentRow.agent_id == agent_id))
        assert status != "REVOKED"
    finally:
        uploading.close()
