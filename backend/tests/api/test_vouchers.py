"""P14.1: voucher detail (FR-DD-1's last level, DR-UDF-2), its audit history, and the
options behind the FR-4.3 filter pickers."""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.company import User
from app.models.config import CustomFieldMapping
from app.models.enums import CollectionType, RoleName
from tests.analytics.books import Books, make_books
from tests.api.test_analytics import get
from tests.factories import DEFAULT_ENTRIES as SALE
from tests.factories import auth_header, make_user


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
async def viewer(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.ACCOUNTANT)


def voucher_url(books: Books, voucher_id: Any) -> str:
    return f"/companies/{books.company.company_id}/vouchers/{voucher_id}"


@pytest.mark.req_partial("DR-UDF-2")  # exports: tests/api/test_exports.py (AC-61)
async def test_a_voucher_shows_every_part_and_its_custom_fields(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    voucher = await books.voucher(
        "Sales",
        date(2025, 5, 2),
        [
            ("Customer A", "DEBIT", "1180"),
            ("Sales", "CREDIT", "1000"),
            ("Output GST", "CREDIT", "180"),
        ],
        bills=[(0, "NEW_REF", "INV-7", "1180", date(2025, 6, 1))],
        items=[("Soap", "10", "100", "1000")],
        centres=[(1, "Retail", "600")],
        number="INV-7",
    )
    voucher.narration = "Diwali order"
    voucher.custom_fields = {"salesman": "Ravi", "unmapped_now": "x"}
    books.session.add(
        CustomFieldMapping(
            company_id=books.company.company_id,
            collection_type=CollectionType.VOUCHER,
            tally_field="TA_Salesman",
            field_key="salesman",
            data_type="TEXT",
        )
    )
    await books.session.flush()

    body = await get(api, viewer, voucher_url(books, voucher.voucher_id))
    assert body["voucher_number"] == "INV-7"
    assert body["voucher_type_name"] == "Sales"
    assert body["status"] == "ACTIVE"
    assert body["narration"] == "Diwali order"
    entries = body["entries"]
    assert [(e["ledger_name"], e["direction"], e["amount"]) for e in entries] == [
        ("Customer A", "Dr", Decimal(1180)),
        ("Sales", "Cr", Decimal(1000)),
        ("Output GST", "Cr", Decimal(180)),
    ]
    assert entries[0]["bills"] == [
        {
            "allocation_type": "NEW_REF",
            "reference_name": "INV-7",
            "due_date": "2025-06-01",
            "amount": Decimal(1180),
            "direction": "Dr",
        }
    ]
    assert [(c["cost_centre_name"], c["amount"]) for c in entries[1]["cost_centres"]] == [
        ("Retail", Decimal(600))
    ]
    assert [
        (i["stock_item_name"], i["quantity"], i["unit"], i["amount"]) for i in body["items"]
    ] == [("Soap", "10.000000", "Nos", Decimal(1000))]
    # mapped fields first with their Tally field; a stored value whose mapping is gone still shows
    assert body["custom_fields"] == [
        {"field_key": "salesman", "tally_field": "TA_Salesman", "value": "Ravi"},
        {"field_key": "unmapped_now", "tally_field": None, "value": "x"},
    ]
    assert "amount_raw" not in str(body)


async def test_a_cancelled_voucher_still_opens_with_its_status(
    api: httpx.AsyncClient, books: Books, viewer: User
) -> None:
    voucher = await books.voucher("Sales", date(2025, 5, 2), SALE, status="CANCELLED")
    body = await get(api, viewer, voucher_url(books, voucher.voucher_id))
    assert body["status"] == "CANCELLED"


async def test_another_companys_voucher_is_not_found(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, viewer: User
) -> None:
    other = await make_books(session, name="Other Traders")
    theirs = await other.voucher("Sales", date(2025, 5, 2), SALE)
    for voucher_id in (theirs.voucher_id, "00000000-0000-4000-8000-000000000000"):
        r = await api.get(voucher_url(books, voucher_id), headers=auth_header(viewer))
        assert r.status_code == 404, r.text


async def test_a_vouchers_audit_history(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    owner = await make_user(session, books.company, RoleName.OWNER)
    accountant = await make_user(session, books.company, RoleName.ACCOUNTANT)
    voucher = await books.voucher("Sales", date(2025, 5, 2), SALE)
    for action in ("VOUCHER_MODIFIED", "VOUCHER_CANCELLED"):
        await audit.record(
            session,
            company_id=books.company.company_id,
            user_id=None,
            action=action,
            entity_type="voucher",
            entity_id=str(voucher.voucher_id),
            before={"status": "ACTIVE"},
            after={"status": "CANCELLED"},
        )
    await audit.record(
        session,
        company_id=books.company.company_id,
        user_id=None,
        action="VOUCHER_MODIFIED",
        entity_type="voucher",
        entity_id="someone-else",
    )
    path = f"/companies/{books.company.company_id}/audit"
    params = {"entity_type": "voucher", "entity_id": str(voucher.voucher_id)}
    r = await api.get(path, params=params, headers=auth_header(owner))
    assert r.status_code == 200, r.text
    assert sorted(e["action"] for e in r.json()) == ["VOUCHER_CANCELLED", "VOUCHER_MODIFIED"]
    assert r.json()[0]["before"] == {"status": "ACTIVE"}
    # SRS 14.1: viewing logs is Owner / Admin
    r = await api.get(path, params=params, headers=auth_header(accountant))
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("kind", "q", "expected"),
    [
        ("customer", None, ["Customer A", "Customer B"]),
        ("customer", "b", ["Customer B"]),
        ("product", "o", ["Soap"]),
        ("cost_centre", None, ["Online", "Retail"]),
    ],
)
async def test_filter_options_list_this_companys_masters(
    api: httpx.AsyncClient,
    session: AsyncSession,
    books: Books,
    viewer: User,
    kind: str,
    q: str | None,
    expected: list[str],
) -> None:
    await make_books(session, name="Other Traders")  # same names, never listed
    path = f"/companies/{books.company.company_id}/masters/options"
    r = await api.get(
        path, params={"kind": kind, **({"q": q} if q else {})}, headers=auth_header(viewer)
    )
    assert r.status_code == 200, r.text
    assert [o["name"] for o in r.json()] == expected
    # a shared link carries only the id: the picker finds its name by id
    first = r.json()[0]
    r = await api.get(path, params={"kind": kind, "id": first["id"]}, headers=auth_header(viewer))
    assert r.json() == [first]
