"""P2.5: companies (D-006, SRS 16 "financial year not configured")."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import AuditLog
from app.models.enums import RoleName
from tests.factories import auth_header, make_company, make_user

NEW = {
    "name": "Sharma Traders",
    "financial_year_start": "2024-04-01",
    "company_timezone": "Asia/Kolkata",
}


async def test_creator_becomes_owner_and_company_starts_inactive(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session)
    headers = auth_header(user)
    r = await api.post("/companies", json=NEW, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_active"] is False
    assert body["my_roles"] == ["OWNER"]
    got = await api.get(f"/companies/{body['company_id']}", headers=headers)
    assert got.status_code == 200
    assert got.json()["name"] == "Sharma Traders"
    audit = (await session.execute(select(AuditLog.action))).scalars().all()
    assert "COMPANY_CREATED" in audit


async def test_list_shows_only_my_companies_with_my_roles(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    mine, other = await make_company(session, name="Mine"), await make_company(session)
    user = await make_user(session, mine, RoleName.ACCOUNTANT, RoleName.ADMIN)
    await make_user(session, other, RoleName.OWNER)
    r = await api.get("/companies", headers=auth_header(user))
    assert r.status_code == 200
    assert [(c["name"], c["my_roles"]) for c in r.json()] == [("Mine", ["ACCOUNTANT", "ADMIN"])]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_timezone", "Mars/Olympus"),
        ("company_timezone", "IST"),  # not an IANA zone name
        ("company_timezone", ""),
        ("financial_year_start", "2023-02-29"),  # not a real date
        ("financial_year_start", "2024-04-31"),
        ("financial_year_start", "2024-01-31"),  # D-034: day 1-28 only
        ("financial_year_start", "April"),
    ],
)
async def test_invalid_timezone_or_fy_start_is_422(
    api: httpx.AsyncClient, session: AsyncSession, field: str, value: str
) -> None:
    company = await make_company(session)
    headers = auth_header(await make_user(session, company, RoleName.OWNER))
    assert (
        await api.post("/companies", json=NEW | {field: value}, headers=headers)
    ).status_code == 422
    r = await api.put(f"/companies/{company.company_id}", json={field: value}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


async def test_update_is_audited_with_changed_fields_only(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    company = await make_company(session, tz="Asia/Kolkata")
    headers = auth_header(await make_user(session, company, RoleName.ADMIN))
    r = await api.put(
        f"/companies/{company.company_id}",
        json={"company_timezone": "Asia/Dubai", "name": company.name},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["company_timezone"] == "Asia/Dubai"
    row = (
        await session.execute(select(AuditLog).where(AuditLog.action == "COMPANY_UPDATED"))
    ).scalar_one()
    assert (row.before_value, row.after_value) == (
        {"company_timezone": "Asia/Kolkata"},
        {"company_timezone": "Asia/Dubai"},
    )
