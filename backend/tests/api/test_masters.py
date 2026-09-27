"""P6.7: resolved groups and voucher types (SRS 19.2 masters)."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RoleName
from tests.factories import (
    auth_header,
    make_company,
    make_group,
    make_predefined_groups,
    make_user,
    make_voucher_type,
)


async def test_groups_show_their_anchor_primary_group_and_nature_by_current_name(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    company = await make_company(session, tally_guid="guid-1")
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    groups = await make_predefined_groups(session, company)
    groups["Sundry Debtors"].name = "Customers"  # renamed in Tally: shown by its current name
    await make_group(session, company, "Retail", groups["Sundry Debtors"])
    other = await make_company(session, tally_guid="guid-2")
    await make_predefined_groups(session, other)
    await session.flush()
    r = await api.get(
        f"/companies/{company.company_id}/masters/groups", headers=auth_header(accountant)
    )
    assert r.status_code == 200, r.text
    body = {g["name"]: g for g in r.json()}
    assert len(body) == 29  # this company's only
    assert {
        k: body["Retail"][k] for k in ("anchor", "predefined_group", "primary_group", "nature")
    } == {
        "anchor": "Customers",
        "predefined_group": "Customers",
        "primary_group": "Current Assets",
        "nature": "ASSET",
    }
    assert body["Retail"]["parent_group_id"] == str(groups["Sundry Debtors"].group_id)
    assert (body["Customers"]["reserved_name"], body["Customers"]["is_predefined"]) == (
        "Sundry Debtors",
        True,
    )


async def test_voucher_types_show_their_base_type(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    company = await make_company(session, tally_guid="guid-1")
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    sales = await make_voucher_type(session, company, "Sales")
    await make_voucher_type(session, company, "POS Invoice", parent=sales)
    r = await api.get(
        f"/companies/{company.company_id}/masters/voucher-types", headers=auth_header(accountant)
    )
    assert [(t["name"], t["base_voucher_type"], t["parent_voucher_type_id"]) for t in r.json()] == [
        ("POS Invoice", "SALES", str(sales.voucher_type_id)),
        ("Sales", "SALES", None),
    ]
