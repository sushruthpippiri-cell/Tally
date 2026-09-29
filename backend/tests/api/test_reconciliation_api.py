"""P10.6: the reconciliation API (REC-1.2, REC-1.4, AC-40), the home status (FR-4.1) and the
uptime advisory (AGT-6.4)."""

from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import AgentCommand
from app.models.enums import RoleName
from tests.analytics.books import Books, make_books
from tests.factories import auth_header, make_company, make_registered_agent, make_user
from tests.reconciliation.tally import Tally

AUG = date(2025, 8, 14)


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


def _url(books: Books, tail: str = "") -> str:
    return f"/companies/{books.company.company_id}/reconciliation{tail}"


async def _failing_run(books: Books) -> Tally:
    """Tally ₹100,000 of sales, local ₹100,012: a FAIL on the totals (SRS 9.3 row 3)."""
    await books.voucher(
        "Sales", AUG, [("Customer A", "DEBIT", "100012"), ("Sales", "CREDIT", "100012")]
    )
    tally = await Tally.new(books)
    tally.total("Sales", "Sales", AUG, credit="100000")
    tally.closings({"Customer A": "100012", "Sales": "-100012"})
    await tally.reconcile()
    return tally


@pytest.mark.req("AC-40", "REC-1.2")
async def test_a_run_shows_tally_local_both_differences_and_the_result(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    tally = await _failing_run(books)
    owner = await make_user(session, books.company, RoleName.ACCOUNTANT)
    body = (await api.get(_url(books), headers=auth_header(owner))).json()
    assert body["run"]["sync_run_id"] == str(tally.run.sync_run_id)
    assert body["run"]["overall"] == "FAIL"
    first = body["rows"][0]  # failures first
    assert {k: first[k] for k in ("metric", "tally_value", "local_value", "result")} == {
        "metric": "SALES_CREDITS",
        "tally_value": "100000.0000",
        "local_value": "100012.0000",
        "result": "FAIL",
    }
    assert (first["absolute_difference"], first["percentage_difference"]) == (
        "12.0000",
        "0.012000",
    )
    assert body["total_rows"] == body["run"]["compared"]
    assert body["unverified_gates"] == ["G18", "G19", "G21", "G23", "G36", "G37"]
    assert [h["sync_run_id"] for h in body["history"]] == [str(tally.run.sync_run_id)]
    ledger_rows = [r for r in body["rows"] if r["metric"] == "LEDGER_BALANCE"]
    assert {r["entity_name"] for r in ledger_rows} >= {"Customer A", "Sales"}


async def test_only_failures_and_paging(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    await _failing_run(books)
    owner = await make_user(session, books.company, RoleName.OWNER)
    failures = (
        await api.get(_url(books), params={"only_failures": True}, headers=auth_header(owner))
    ).json()
    assert failures["total_rows"] == failures["run"]["failed"] == len(failures["rows"])
    assert {r["result"] for r in failures["rows"]} == {"FAIL"}
    page = (
        await api.get(_url(books), params={"offset": 1, "limit": 2}, headers=auth_header(owner))
    ).json()
    assert len(page["rows"]) == 2 and page["total_rows"] > 2


async def test_no_run_yet_and_unknown_or_foreign_runs(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    owner = await make_user(session, books.company, RoleName.OWNER)
    empty = (await api.get(_url(books), headers=auth_header(owner))).json()
    assert (empty["run"], empty["rows"], empty["history"]) == (None, [], [])
    other = await make_books(session, "Other Traders")
    foreign = await _failing_run(other)
    r = await api.get(
        _url(books), params={"run_id": str(foreign.run.sync_run_id)}, headers=auth_header(owner)
    )
    assert (r.status_code, r.json()["code"]) == (404, "NOT_FOUND")  # SEC-1.7


@pytest.mark.req_partial("REC-1.4")  # on demand; after FULL and daily: tests/jobs
async def test_reconcile_now_creates_a_reconciliation_command(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    company = await make_company(session, tally_guid="guid-now")
    agent, _ = await make_registered_agent(session, company)
    owner = await make_user(session, company, RoleName.ACCOUNTANT)
    r = await api.post(
        f"/companies/{company.company_id}/reconciliation/run", json={}, headers=auth_header(owner)
    )
    assert r.status_code == 201, r.text
    assert (r.json()["agent_id"], r.json()["sync_mode"]) == (str(agent.agent_id), "RECONCILIATION")
    command = await session.get(AgentCommand, r.json()["command_id"])
    assert command is not None and command.status == "PENDING"


@pytest.mark.req_partial("FR-4.1")  # the reconciliation status; the rest of the home view: P13
async def test_the_sync_status_carries_the_latest_reconciliation(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    owner = await make_user(session, books.company, RoleName.OWNER)
    url = f"/companies/{books.company.company_id}/sync/status"
    assert (await api.get(url, headers=auth_header(owner))).json()["reconciliation"] is None
    tally = await _failing_run(books)
    status = (await api.get(url, headers=auth_header(owner))).json()["reconciliation"]
    assert (status["sync_run_id"], status["overall"]) == (str(tally.run.sync_run_id), "FAIL")


@pytest.mark.req("AGT-6.4")
async def test_the_uptime_advisory_is_prominent_after_a_failed_reconciliation(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    owner = await make_user(session, books.company, RoleName.OWNER)
    await make_registered_agent(session, books.company, "Long", tally_uptime_seconds=8 * 86_400)
    await make_registered_agent(session, books.company, "Fresh", tally_uptime_seconds=3600)
    url = f"/companies/{books.company.company_id}/agents"

    async def levels() -> dict[str, str]:
        agents = (await api.get(url, headers=auth_header(owner))).json()["agents"]
        return {
            a["agent_name"]: a["uptime_advisory"]
            for a in agents
            if a["agent_name"] in ("Long", "Fresh")
        }

    assert await levels() == {"Long": "advisory", "Fresh": "none"}
    await _failing_run(books)
    assert await levels() == {"Long": "prominent", "Fresh": "none"}
