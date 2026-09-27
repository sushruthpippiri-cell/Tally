"""P5.1: sync runs, the plan, and the lease (SRS 6.3, AC-07, D-039)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gates
from app.models.agents import Agent
from app.models.company import Company
from app.models.enums import CommandStatus, SyncMode
from app.models.sync import SyncRun, SyncWatermark
from tests.factories import (
    agent_header,
    make_company,
    make_registered_agent,
    make_running_command,
    make_sync_run,
)


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tally_guid="guid-1")


@pytest.fixture
async def agent(session: AsyncSession, company: Company) -> tuple[Agent, str]:
    return await make_registered_agent(session, company)


async def _post(
    api: httpx.AsyncClient, credential: str, path: str, **body: object
) -> httpx.Response:
    return await api.post(path, json=body or None, headers=agent_header(credential))


def _lease(run: SyncRun, collection: str = "VOUCHER") -> dict[str, str]:
    return {"sync_run_id": str(run.sync_run_id), "collection_type": collection}


async def _watermark(session: AsyncSession, company: Company, collection: str, value: int) -> None:
    session.add(
        SyncWatermark(
            company_id=company.company_id,
            collection_type=collection,
            last_alter_id=value,
            status="OK",
        )
    )
    await session.flush()


@pytest.mark.req_partial("AC-07", "SYNC-1.1")  # the ingest side: P5.5 tests
async def test_the_plan_gives_each_collection_its_own_watermark(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, agent: tuple[Agent, str]
) -> None:
    row, credential = agent
    await _watermark(session, company, "VOUCHER", 500)
    await _watermark(session, company, "LEDGER", 50)
    command = await make_running_command(session, row, SyncMode.INCREMENTAL)
    r = await _post(api, credential, f"/agent/commands/{command.command_id}/runs")
    assert r.status_code == 201, r.text
    plan = r.json()["collections"]
    assert (plan["VOUCHER"]["watermark"], plan["VOUCHER"]["full"]) == (500, False)
    assert (plan["LEDGER"]["watermark"], plan["LEDGER"]["full"]) == (50, False)
    assert plan["GROUP"]["full"] is True  # never synced -> full
    run = await session.get(SyncRun, r.json()["sync_run_id"])
    assert run is not None and run.status == "IN_PROGRESS" and run.sync_mode == "INCREMENTAL"


@pytest.mark.req_partial("AC-12", "VAL-1.2")  # the batch side (GATE_NOT_PASSED): P5.9
async def test_a_failed_gate_makes_its_collection_full_only(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    agent: tuple[Agent, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, credential = agent
    await _watermark(session, company, "VOUCHER", 500)
    failed = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G3": "FAILED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: failed)
    command = await make_running_command(session, row, SyncMode.INCREMENTAL)
    plan = (await _post(api, credential, f"/agent/commands/{command.command_id}/runs")).json()
    assert plan["collections"]["VOUCHER"] == {
        "mode": "FULL_ONLY",
        "watermark": 500,
        "full": True,
        "key_list_due": True,
    }


@pytest.mark.parametrize("status", [CommandStatus.CLAIMED, CommandStatus.FAILED_AGENT_LOST])
async def test_only_a_running_command_may_start_a_run(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str], status: CommandStatus
) -> None:
    row, credential = agent
    command = await make_running_command(session, row)
    command.status = status
    await session.flush()
    r = await _post(api, credential, f"/agent/commands/{command.command_id}/runs")
    assert (r.status_code, r.json()["code"]) == (409, "INVALID_COMMAND_STATE")


@pytest.mark.req_partial("SYNC-4.1", "SYNC-4.2")  # the race itself: tests/races
async def test_a_held_lease_refuses_another_agent_by_name(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, agent: tuple[Agent, str]
) -> None:
    a, a_cred = agent
    b, b_cred = await make_registered_agent(session, company, "Branch")
    run_a = await make_sync_run(session, await make_running_command(session, a))
    run_b = await make_sync_run(session, await make_running_command(session, b))
    got = await _post(api, a_cred, "/agent/leases/acquire", **_lease(run_a))
    assert got.status_code == 200, got.text
    refused = await _post(api, b_cred, "/agent/leases/acquire", **_lease(run_b))
    assert (refused.status_code, refused.json()["code"]) == (409, "SYNC_LOCKED")
    assert refused.json()["details"]["holder"] == a.agent_name
    other = await _post(api, b_cred, "/agent/leases/acquire", **_lease(run_b, "LEDGER"))
    assert other.status_code == 200  # a different collection is independent


@pytest.mark.req("SYNC-4.3")
async def test_a_lease_is_released_on_completion_or_reclaimed_after_expiry(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, agent: tuple[Agent, str]
) -> None:
    a, a_cred = agent
    b, b_cred = await make_registered_agent(session, company, "Branch")
    start = datetime.now(UTC)
    # a's command stays alive for an hour; b's command lease is the usual 300 s.
    command_a = await make_running_command(session, a, lease_expires_at=start + timedelta(hours=1))
    run_a = await make_sync_run(session, command_a)
    run_b = await make_sync_run(session, await make_running_command(session, b))
    with time_machine.travel(start, tick=False):
        await _post(api, a_cred, "/agent/leases/acquire", **_lease(run_a))
        released = await _post(api, a_cred, "/agent/leases/release", **_lease(run_a))
        assert released.status_code == 200  # released on completion
        assert (
            await _post(api, b_cred, "/agent/leases/acquire", **_lease(run_b))
        ).status_code == 200
    with time_machine.travel(start + timedelta(seconds=299), tick=False):
        refused = await _post(api, a_cred, "/agent/leases/acquire", **_lease(run_a))
        assert refused.status_code == 409  # b's lease is still live
    with time_machine.travel(start + timedelta(seconds=301), tick=False):
        taken = await _post(api, a_cred, "/agent/leases/acquire", **_lease(run_a))
        assert taken.status_code == 200  # b's lease expired: reclaimed automatically


async def test_progress_renews_the_agents_leases_and_result_releases_them(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, agent: tuple[Agent, str]
) -> None:
    a, a_cred = agent
    command = await make_running_command(session, a)
    run = await make_sync_run(session, command)
    start = datetime.now(UTC)
    with time_machine.travel(start, tick=False):
        await _post(api, a_cred, "/agent/leases/acquire", **_lease(run))
    with time_machine.travel(start + timedelta(seconds=200), tick=False):
        assert (
            await _post(api, a_cred, f"/agent/commands/{command.command_id}/progress")
        ).status_code == 200
    mark = (
        await session.execute(select(SyncWatermark).execution_options(populate_existing=True))
    ).scalar_one()
    assert mark.lock_expires_at == start + timedelta(seconds=500)
    with time_machine.travel(start + timedelta(seconds=210), tick=False):
        done = await _post(
            api, a_cred, f"/agent/commands/{command.command_id}/result", status="COMPLETED"
        )
    assert done.status_code == 200
    mark = (
        await session.execute(select(SyncWatermark).execution_options(populate_existing=True))
    ).scalar_one()
    assert mark.locked_by_agent_id is None


async def test_finish_marks_the_run_and_releases_leases(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    a, a_cred = agent
    command = await make_running_command(session, a)
    run = await make_sync_run(session, command)
    await _post(api, a_cred, "/agent/leases/acquire", **_lease(run))
    skipped = {"collection_type": "LEDGER", "code": "SYNC_LOCKED", "message": "held by B"}
    r = await _post(
        api,
        a_cred,
        f"/agent/commands/{command.command_id}/runs/{run.sync_run_id}/finish",
        status="COMPLETED",
        problems=[skipped],
    )
    assert r.json()["status"] == "PARTIAL"  # D-040 #1: a collection was not synced
    mark = (
        await session.execute(select(SyncWatermark).execution_options(populate_existing=True))
    ).scalar_one()
    assert mark.locked_by_agent_id is None


async def test_the_plan_gives_todays_date_in_the_company_time_zone_and_books_beginning(
    api: httpx.AsyncClient, session: AsyncSession, agent: tuple[Agent, str]
) -> None:
    """D-042 #5 (owner): the snapshot date and date pages come from the backend."""
    from datetime import date

    row, credential = agent
    company = await session.get(Company, row.company_id)
    assert company is not None
    company.company_timezone, company.books_from = "Asia/Kolkata", date(2023, 4, 1)
    command = await make_running_command(session, row)
    with time_machine.travel(datetime(2026, 3, 16, 20, 0, tzinfo=UTC), tick=False):
        plan = (await _post(api, credential, f"/agent/commands/{command.command_id}/runs")).json()
    assert (plan["as_of"], plan["full_pull_from"]) == ("2026-03-17", "2023-04-01")  # 01:30 IST
