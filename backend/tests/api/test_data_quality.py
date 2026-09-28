"""P6.6: the Data Quality view (FR-4.5, D-041 #9): the registry, paging, tenancy and the
checks not covered by the sync tests (test_hierarchy.py, test_key_lists.py,
test_ingest_vouchers.py)."""

from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gates
from app.models.company import Company, User
from app.models.config import CompanySetting
from app.models.enums import RoleName, SettingDataType
from app.services.data_quality import CHECKS
from tests.factories import (
    auth_header,
    make_company,
    make_cost_centre,
    make_group,
    make_ledger,
    make_opening_balance,
    make_predefined_groups,
    make_user,
)

BOOKS_FROM = date(2023, 4, 1)


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    company = await make_company(session, tally_guid="guid-1")
    company.books_from = BOOKS_FROM
    return company


@pytest.fixture
async def accountant(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.ACCOUNTANT)  # everyone may view (SRS 14)


def _url(company: Company, path: str = "") -> str:
    return f"/companies/{company.company_id}/data-quality{path}"


async def _items(
    api: httpx.AsyncClient, company: Company, user: User, check: str, **params: int
) -> httpx.Response:
    return await api.get(_url(company, f"/{check}"), params=params, headers=auth_header(user))


@pytest.mark.req_partial("FR-4.5")  # unsupported allocations: P11
async def test_every_check_runs_and_a_new_company_has_nothing_to_report(
    api: httpx.AsyncClient, company: Company, accountant: User
) -> None:
    r = await api.get(_url(company), headers=auth_header(accountant))
    assert r.status_code == 200, r.text
    assert {c["check_id"]: c["count"] for c in r.json()} == dict.fromkeys(CHECKS, 0)
    for check in CHECKS:  # every item query runs, too
        assert (await _items(api, company, accountant, check)).json()["items"] == []


async def test_items_are_paged_and_scoped_to_the_company(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, accountant: User
) -> None:
    for name in ("North", "South", "West"):
        centre = await make_cost_centre(session, company, name)
        centre.status = "MISSING_IN_TALLY"
    other = await make_company(session, tally_guid="guid-2")
    (await make_cost_centre(session, other, "Elsewhere")).status = "MISSING_IN_TALLY"
    await session.flush()
    first = (await _items(api, company, accountant, "missing_masters", limit=2)).json()
    assert (first["count"], [i["name"] for i in first["items"]]) == (3, ["North", "South"])
    rest = (await _items(api, company, accountant, "missing_masters", limit=2, offset=2)).json()
    assert [i["name"] for i in rest["items"]] == ["West"]
    assert (await _items(api, company, accountant, "no_such_check")).status_code == 404


async def test_the_renamed_checks_retire_once_g32_passes(
    api: httpx.AsyncClient, company: Company, accountant: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    passed = {g: "NOT_TESTED" for g in gates.load_gate_status()} | {"G32": "PASSED"}
    monkeypatch.setattr(gates, "_default_statuses", lambda: passed)
    listed = {
        c["check_id"]
        for c in (await api.get(_url(company), headers=auth_header(accountant))).json()
    }
    retired = {"predefined_group_possibly_renamed", "predefined_voucher_type_possibly_renamed"}
    assert listed == set(CHECKS) - retired
    for check in retired:
        assert (await _items(api, company, accountant, check)).status_code == 404


async def test_an_allow_list_entry_for_a_group_no_longer_in_tally_is_reported(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, accountant: User
) -> None:
    await make_predefined_groups(session, company)
    session.add(
        CompanySetting(
            company_id=company.company_id,
            setting_key="classification.sales_groups",
            setting_value=[
                {"type": "PREDEFINED", "reserved_name": "Sales Accounts"},
                {"type": "COMPANY_GROUP", "tally_guid": "guid-deleted-in-tally"},
            ],
            data_type=SettingDataType.JSON,
        )
    )
    await session.flush()
    items = (await _items(api, company, accountant, "stale_allow_list_entries")).json()["items"]
    assert items == [
        {
            "setting_key": "classification.sales_groups",
            "entry_type": "COMPANY_GROUP",
            "identifier": "guid-deleted-in-tally",
        }
    ]


async def test_balance_sheet_ledgers_without_a_books_beginning_opening_are_listed(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, accountant: User
) -> None:
    groups = await make_predefined_groups(session, company)
    await make_ledger(session, company, "No Opening", groups["Sundry Debtors"])
    with_opening = await make_ledger(session, company, "Has Opening", groups["Sundry Debtors"])
    await make_opening_balance(session, company, with_opening, "DEBIT", "500", BOOKS_FROM)
    await make_ledger(session, company, "Sales", groups["Sales Accounts"])  # income: no opening
    schemes = await make_group(session, company, "Government Schemes", None, nature="ASSET")  # type: ignore[arg-type]
    await make_ledger(session, company, "Subsidy", schemes)
    items = (await _items(api, company, accountant, "ledgers_without_opening_balance")).json()[
        "items"
    ]
    assert [(i["name"], i["nature"]) for i in items] == [
        ("No Opening", "ASSET"),
        ("Subsidy", "ASSET"),
    ]
