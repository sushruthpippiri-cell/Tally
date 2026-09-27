"""P5.8: sync status, runs, errors, lease status and custom-field mappings (SRS 19.2)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import CommandStatus, RoleName
from app.models.sync import SyncError, SyncRun, SyncWatermark
from tally_contract.udf import UdfMapping, generate_tdl
from tests.factories import (
    auth_header,
    make_company,
    make_registered_agent,
    make_running_command,
    make_sync_run,
    make_user,
)


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session, tally_guid="guid-1")


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER)


@pytest.fixture
async def agent(session: AsyncSession, company: Company) -> Agent:
    row, _ = await make_registered_agent(session, company, "Head Office")
    return row


def _url(company: Company, path: str) -> str:
    return f"/companies/{company.company_id}{path}"


async def _run(session: AsyncSession, agent: Agent, started: datetime, **fields: object) -> SyncRun:
    command = await make_running_command(session, agent)
    run = await make_sync_run(session, command)
    command.status = CommandStatus.COMPLETED  # one active command per Agent
    run.started_at = started
    for key, value in fields.items():
        setattr(run, key, value)
    await session.flush()
    return run


def _error(run: SyncRun, code: str, **fields: object) -> SyncError:
    values: dict[str, object] = {"entity_type": "VOUCHER", "message": code} | fields
    return SyncError(
        company_id=run.company_id, sync_run_id=run.sync_run_id, error_code=code, **values
    )


async def test_status_shows_each_collection_its_lease_and_what_holds_it_back(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User, agent: Agent
) -> None:
    now = datetime.now(UTC)
    run = await _run(session, agent, now, status="PARTIAL")
    session.add_all(
        [
            SyncWatermark(
                company_id=company.company_id,
                collection_type="VOUCHER",
                last_alter_id=500,
                status="OK",
                last_successful_sync_at=now,
                locked_by_agent_id=agent.agent_id,
                lock_acquired_at=now,
                lock_expires_at=now + timedelta(minutes=5),
            ),
            SyncWatermark(
                company_id=company.company_id,
                collection_type="LEDGER",
                last_alter_id=50,
                status="OK",
                locked_by_agent_id=agent.agent_id,
                lock_expires_at=now - timedelta(minutes=1),  # expired
            ),
            _error(
                run, "UNKNOWN_MASTER_REFERENCE", tally_guid="v-1", alter_id=510, watermark_hold=509
            ),
        ]
    )
    # Another company's sync state is never shown.
    other = await make_company(session, tally_guid="guid-2")
    session.add(
        SyncWatermark(company_id=other.company_id, collection_type="GROUP", last_alter_id=9)
    )
    await session.flush()

    body = (await api.get(_url(company, "/sync/status"), headers=auth_header(owner))).json()
    by = {c["collection_type"]: c for c in body["collections"]}
    assert set(by) == {
        "COMPANY",
        "GROUP",
        "LEDGER",
        "VOUCHER_TYPE",
        "STOCK_ITEM",
        "COST_CENTRE",
        "VOUCHER",
    }
    voucher = by["VOUCHER"]
    assert (voucher["watermark"], voucher["status"], voucher["held_back"]) == (500, "OK", 1)
    assert (voucher["lease_holder"], voucher["label"]) == ("Head Office", "Incremental")
    assert (by["LEDGER"]["watermark"], by["LEDGER"]["lease_holder"]) == (50, None)  # expired
    assert (by["GROUP"]["watermark"], by["GROUP"]["status"]) == (0, "NEVER_SYNCED")
    assert body["last_run"]["sync_run_id"] == str(run.sync_run_id)
    assert body["warnings"] and body["warnings"][0].startswith("INITIAL_SYNC_INCOMPLETE")

    leases = (await api.get(_url(company, "/sync/lease-status"), headers=auth_header(owner))).json()
    assert {(x["collection_type"], x["holder_name"], x["live"]) for x in leases} == {
        ("VOUCHER", "Head Office", True),
        ("LEDGER", "Head Office", False),  # reclaimable (SYNC-4.3)
    }


async def test_runs_are_listed_newest_first_a_page_at_a_time(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User, agent: Agent
) -> None:
    now = datetime.now(UTC)
    runs = [await _run(session, agent, now - timedelta(hours=h)) for h in (3, 2, 1)]
    other = await make_company(session, tally_guid="guid-2")
    other_agent, _ = await make_registered_agent(session, other)
    await _run(session, other_agent, now)
    url, header = _url(company, "/sync/runs"), auth_header(owner)
    first = (await api.get(url, params={"limit": 2}, headers=header)).json()
    assert [r["sync_run_id"] for r in first] == [str(runs[2].sync_run_id), str(runs[1].sync_run_id)]
    rest = (
        await api.get(url, params={"limit": 2, "before": first[-1]["started_at"]}, headers=header)
    ).json()
    assert [r["sync_run_id"] for r in rest] == [str(runs[0].sync_run_id)]


async def test_errors_filter_by_run_and_code_and_need_view_logs(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User, agent: Agent
) -> None:
    now = datetime.now(UTC)
    a, b = await _run(session, agent, now), await _run(session, agent, now)
    session.add_all(
        [
            _error(a, "STALE_ALTERID"),
            _error(a, "UNKNOWN_MASTER_REFERENCE"),
            _error(b, "UNKNOWN_MASTER_REFERENCE"),
        ]
    )
    await session.flush()
    url, header = _url(company, "/sync/errors"), auth_header(owner)
    in_a = (await api.get(url, params={"sync_run_id": str(a.sync_run_id)}, headers=header)).json()
    assert sorted(e["error_code"] for e in in_a) == ["STALE_ALTERID", "UNKNOWN_MASTER_REFERENCE"]
    unknown = (
        await api.get(url, params={"code": "UNKNOWN_MASTER_REFERENCE"}, headers=header)
    ).json()
    assert len(unknown) == 2
    page = (await api.get(url, params={"limit": 1}, headers=header)).json()
    nxt = (await api.get(url, params={"limit": 5, "before": page[0]["id"]}, headers=header)).json()
    assert len(page) + len(nxt) == 3
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    assert (await api.get(url, headers=auth_header(accountant))).status_code == 403


VOUCHER_REGION = {
    "collection_type": "VOUCHER",
    "tally_field": "Region",
    "field_key": "region",
    "data_type": "TEXT",
}
LEDGER_GSTIN = {
    "collection_type": "LEDGER",
    "tally_field": "PartyGSTIN",
    "field_key": "gstin",
    "data_type": "TEXT",
}


@pytest.mark.req("DR-UDF-1", "DR-UDF-4")
async def test_custom_fields_are_off_by_default_mapped_by_owners_and_admins_and_generate_the_tdl(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    admin = await make_user(session, company, RoleName.ADMIN)
    url, header = _url(company, "/settings/custom-fields"), auth_header(admin)
    assert (await api.get(url, headers=header)).json() == []  # nothing extracted by default
    assert (await api.get(f"{url}/tdl", headers=header)).text == generate_tdl([])

    r = await api.put(url, json={"mappings": [VOUCHER_REGION, LEDGER_GSTIN]}, headers=header)
    assert r.status_code == 200, r.text
    r = await api.put(url, json={"mappings": [VOUCHER_REGION]}, headers=header)  # gstin off
    assert [m["field_key"] for m in r.json()] == ["region"]
    tdl = await api.get(f"{url}/tdl", headers=header)
    assert tdl.text == generate_tdl([UdfMapping.model_validate(VOUCHER_REGION)])
    assert "attachment" in tdl.headers["content-disposition"]
    audits = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "CUSTOM_FIELDS_UPDATED")))
        .scalars()
        .all()
    )
    assert len(audits) == 2 and audits[-1].after_value == {"mappings": [VOUCHER_REGION]}

    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    assert (await api.get(url, headers=auth_header(accountant))).status_code == 403


@pytest.mark.parametrize(
    "mappings",
    [
        [VOUCHER_REGION | {"tally_field": "Region; Set As : $$Evil"}],  # not a bare identifier
        [VOUCHER_REGION, VOUCHER_REGION | {"tally_field": "Area"}],  # same key twice
        [VOUCHER_REGION | {"collection_type": "GROUP"}],  # not supported on groups
    ],
)
async def test_bad_mappings_are_refused(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    owner: User,
    mappings: list[dict[str, str]],
) -> None:
    r = await api.put(
        _url(company, "/settings/custom-fields"),
        json={"mappings": mappings},
        headers=auth_header(owner),
    )
    assert r.status_code == 422, r.text
