"""P2.8: settings and feature flags API (SRS 18, D-001, AC-59)."""

from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import Nature, RoleName
from app.services.settings import get_flag, get_setting
from tests.factories import auth_header, make_company, make_group, make_predefined_groups, make_user

SALES = "classification.sales_groups"


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session)


@pytest.fixture
async def admin(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.ADMIN)


def _url(company: Company) -> str:
    return f"/companies/{company.company_id}/settings"


async def _put(api: httpx.AsyncClient, company: Company, user: User, **body: Any) -> httpx.Response:
    return await api.put(_url(company), json=body, headers=auth_header(user))


def _error_keys(r: httpx.Response) -> dict[str, str]:
    assert r.status_code == 422, r.text
    return {e["key"]: e["message"] for e in r.json()["details"]["errors"]}


@pytest.mark.req("AC-59")
async def test_accountant_gets_403_on_settings_and_user_management(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    headers = auth_header(accountant)
    users = f"/companies/{company.company_id}/users"
    calls = [
        api.put(_url(company), json={"settings": {"analytics.top_n_default": 20}}, headers=headers),
        api.get(users, headers=headers),
        api.post(
            users,
            json={
                "email": "x@example.com",
                "name": "x",
                "password": "long-enough",
                "roles": ["OWNER"],
            },
            headers=headers,
        ),
        api.put(f"{users}/{accountant.user_id}", json={"roles": ["OWNER"]}, headers=headers),
    ]
    for call in calls:
        r = await call
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "FORBIDDEN"
    # Nothing changed.
    assert await get_setting(session, company.company_id, "analytics.top_n_default") == 10
    assert (await session.execute(select(AuditLog))).scalars().all() == []


async def test_everyone_reads_defaults_with_is_default(
    api: httpx.AsyncClient, session: AsyncSession, company: Company
) -> None:
    accountant = await make_user(session, company, RoleName.ACCOUNTANT)
    r = await api.get(_url(company), headers=auth_header(accountant))
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["analytics.top_n_default"] == {"value": 10, "is_default": True}
    assert body["feature_flags"] == {
        "FEATURE_ANOMALY_DETECTION": {"enabled": False, "is_default": True}
    }


@pytest.mark.req_partial("LOG-1.1")  # setting and feature-flag changes
async def test_update_stores_override_and_audits_before_after(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User
) -> None:
    r = await _put(
        api,
        company,
        admin,
        settings={"analytics.top_n_default": 25, "reconciliation.money_absolute_tolerance": 2},
        feature_flags={"FEATURE_ANOMALY_DETECTION": True},
    )
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["analytics.top_n_default"] == {"value": 25, "is_default": False}
    assert s["reconciliation.money_absolute_tolerance"]["value"] == "2"
    assert r.json()["feature_flags"]["FEATURE_ANOMALY_DETECTION"]["enabled"] is True
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    assert [(a.action, a.entity_id, a.before_value, a.after_value, a.user_id) for a in rows] == [
        ("SETTING_CHANGED", "analytics.top_n_default", {"value": 10}, {"value": 25}, admin.user_id),
        (
            "SETTING_CHANGED",
            "reconciliation.money_absolute_tolerance",
            {"value": "1.00"},
            {"value": "2"},
            admin.user_id,
        ),
        (
            "FEATURE_FLAG_CHANGED",
            "FEATURE_ANOMALY_DETECTION",
            {"enabled": False},
            {"enabled": True},
            admin.user_id,
        ),
    ]
    assert await get_flag(session, company.company_id, "FEATURE_ANOMALY_DETECTION") is True


async def test_one_bad_value_rejects_the_whole_update(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User
) -> None:
    r = await _put(
        api,
        company,
        admin,
        settings={
            "analytics.top_n_default": 25,
            "aging.bucket_boundaries": [90, 30],
            "no.such.key": 1,
        },
        feature_flags={"FEATURE_TIME_TRAVEL": True},
    )
    assert _error_keys(r).keys() == {
        "aging.bucket_boundaries",
        "no.such.key",
        "FEATURE_TIME_TRAVEL",
    }
    assert await get_setting(session, company.company_id, "analytics.top_n_default") == 10


async def test_flags_are_boolean_only(
    api: httpx.AsyncClient, company: Company, admin: User
) -> None:
    r = await _put(api, company, admin, feature_flags={"FEATURE_ANOMALY_DETECTION": "yes"})
    assert r.status_code == 422


async def test_dead_stock_days_must_exceed_the_stored_slow_threshold(
    api: httpx.AsyncClient, company: Company, admin: User
) -> None:
    assert (
        await _put(api, company, admin, settings={"stock.slow_threshold_days": 150})
    ).status_code == 200
    r = await _put(api, company, admin, settings={"stock.dead_stock_days": 120})
    assert "stock.dead_stock_days" in _error_keys(r)


async def test_get_setting_reads_overrides_and_decimals(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User
) -> None:
    await _put(api, company, admin, settings={"sync.keylist_max_missing_ratio": "0.35"})
    session.info.clear()
    assert await get_setting(session, company.company_id, "sync.keylist_max_missing_ratio") == (
        Decimal("0.35")
    )
    assert await get_setting(session, company.company_id, "anomaly.max_multiplier") is None


# --- allow-lists (D-001) -----------------------------------------------------------------


@pytest.fixture
async def groups(session: AsyncSession, company: Company) -> dict[str, Any]:
    predefined = await make_predefined_groups(session, company)
    top = await make_group(session, company, "Government Schemes", None, Nature.ASSET)
    nested = await make_group(session, company, "Online", predefined["Sales Accounts"])
    return {"predefined": predefined, "top": top, "nested": nested}


async def test_company_top_level_group_is_accepted_and_shown_by_name(
    api: httpx.AsyncClient, company: Company, admin: User, groups: dict[str, Any]
) -> None:
    entries = [
        {"type": "PREDEFINED", "reserved_name": "Sales Accounts"},
        {"type": "COMPANY_GROUP", "tally_guid": groups["top"].tally_guid},
    ]
    r = await _put(api, company, admin, settings={SALES: entries})
    assert r.status_code == 200, r.text
    assert r.json()["settings"][SALES]["value"] == [
        {**entries[0], "display_name": "Sales Accounts", "is_missing": False},
        {**entries[1], "display_name": "Government Schemes", "is_missing": False},
    ]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"type": "COMPANY_GROUP", "tally_guid": "nested"}, "can never be a classification"),
        ({"type": "COMPANY_GROUP", "tally_guid": "unknown-guid"}, "unknown group"),
        ({"type": "COMPANY_GROUP", "tally_guid": "predefined"}, "use the PREDEFINED form"),
        ({"type": "PREDEFINED", "reserved_name": "Online Sales"}, "predefined groups"),
        ("Sales Accounts", "never a display name"),
    ],
)
async def test_invalid_allow_list_entries_are_rejected(
    api: httpx.AsyncClient,
    company: Company,
    admin: User,
    groups: dict[str, Any],
    entry: Any,
    message: str,
) -> None:
    if isinstance(entry, dict) and entry.get("tally_guid") == "nested":
        entry = entry | {"tally_guid": groups["nested"].tally_guid}
    if isinstance(entry, dict) and entry.get("tally_guid") == "predefined":
        entry = entry | {"tally_guid": groups["predefined"]["Sales Accounts"].tally_guid}
    r = await _put(api, company, admin, settings={SALES: [entry]})
    assert message in _error_keys(r)[SALES]


async def test_another_companys_group_looks_exactly_like_an_unknown_one(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, admin: User
) -> None:
    other = await make_company(session, name="Other")
    theirs = await make_group(session, other, "Their Top Group", None, Nature.ASSET)
    r_theirs = await _put(
        api,
        company,
        admin,
        settings={SALES: [{"type": "COMPANY_GROUP", "tally_guid": theirs.tally_guid}]},
    )
    r_unknown = await _put(
        api,
        company,
        admin,
        settings={SALES: [{"type": "COMPANY_GROUP", "tally_guid": "no-such-guid"}]},
    )
    assert _error_keys(r_theirs)[SALES] == f"unknown group {theirs.tally_guid!r}"
    assert _error_keys(r_unknown)[SALES] == "unknown group 'no-such-guid'"


async def test_renamed_groups_still_resolve_and_show_their_new_name(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    admin: User,
    groups: dict[str, Any],
) -> None:
    entries = [
        {"type": "PREDEFINED", "reserved_name": "Sales Accounts"},
        {"type": "COMPANY_GROUP", "tally_guid": groups["top"].tally_guid},
    ]
    assert (await _put(api, company, admin, settings={SALES: entries})).status_code == 200
    groups["top"].name = "Govt Schemes"
    groups["predefined"]["Sales Accounts"].name = "Revenue"  # renamed in Tally (G32)
    await session.flush()
    r = await api.get(_url(company), headers=auth_header(admin))
    shown = r.json()["settings"][SALES]["value"]
    assert [(e["display_name"], e["is_missing"]) for e in shown] == [
        ("Revenue", False),
        ("Govt Schemes", False),
    ]


async def test_entry_for_a_group_gone_from_tally_is_kept_and_marked_missing(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    admin: User,
    groups: dict[str, Any],
) -> None:
    entry = {"type": "COMPANY_GROUP", "tally_guid": groups["top"].tally_guid}
    assert (await _put(api, company, admin, settings={SALES: [entry]})).status_code == 200
    groups["top"].status = "MISSING_IN_TALLY"
    await session.flush()
    r = await api.get(_url(company), headers=auth_header(admin))
    assert r.json()["settings"][SALES]["value"] == [
        {**entry, "display_name": None, "is_missing": True}
    ]
