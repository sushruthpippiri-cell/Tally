"""P1.8: configuration, audit and anomaly tables (SRS 5.10, 5.11, SEC-1.13, D-001)."""

from datetime import date

import psycopg
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.config import AuditLog, CompanySetting
from app.models.defaults import DEFAULT_CLASSIFICATION_ALLOW_LISTS, PREDEFINED_GROUP_NAMES
from app.models.masters import Group
from tests.factories import (
    db_error,
    make_company,
    make_group,
    make_ledger,
    make_predefined_groups,
    make_voucher,
    make_voucher_type,
)

# Resolve a company's allow-list entries to anchors: PREDEFINED by reserved name,
# COMPANY_GROUP by GUID. Never by display name (D-001).
RESOLVE = text("""
    SELECT g.classification_group_id
    FROM company_settings s
    CROSS JOIN LATERAL jsonb_array_elements(s.setting_value) AS e
    JOIN groups g ON g.company_id = s.company_id AND (
        (e->>'type' = 'PREDEFINED' AND g.reserved_name = e->>'reserved_name')
        OR (e->>'type' = 'COMPANY_GROUP' AND g.tally_guid = e->>'tally_guid'))
    WHERE s.company_id = :c AND s.setting_key = :k
    ORDER BY 1
""")

CHANGES = ["UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"]


def test_default_allow_lists_are_tagged_predefined_entries() -> None:
    assert set(DEFAULT_CLASSIFICATION_ALLOW_LISTS) == {
        "classification.sales_groups",
        "classification.purchase_groups",
        "classification.expense_groups",
        "classification.cash_bank_groups",
        "classification.tax_groups",
    }
    for entries in DEFAULT_CLASSIFICATION_ALLOW_LISTS.values():
        for entry in entries:
            assert entry.keys() == {"type", "reserved_name"} and entry["type"] == "PREDEFINED"
            assert entry["reserved_name"] in PREDEFINED_GROUP_NAMES
    assert len(PREDEFINED_GROUP_NAMES) == 28


@pytest.mark.req("ACC-7.3")
async def test_allow_list_entry_survives_group_rename(session: AsyncSession) -> None:
    """D-001 example 5: renaming Sundry Debtors to Customers changes nothing."""
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    debtors = groups["Sundry Debtors"]
    session.add(
        CompanySetting(
            company_id=company.company_id,
            setting_key="classification.customer_groups",
            setting_value=[{"type": "PREDEFINED", "reserved_name": "Sundry Debtors"}],
            data_type="JSON",
        )
    )
    await session.flush()
    params = {"c": company.company_id, "k": "classification.customer_groups"}
    before = (await session.scalars(RESOLVE, params)).all()
    await session.execute(
        update(Group).where(Group.group_id == debtors.group_id).values(name="Customers")
    )
    after = (await session.scalars(RESOLVE, params)).all()
    assert before == after == [debtors.classification_group_id]


@pytest.mark.req("ACC-7.3")
async def test_company_group_entry_resolves_by_guid(session: AsyncSession) -> None:
    """D-001 example 3: a user top-level group is its own anchor and can be allow-listed."""
    company = await make_company(session)
    await make_predefined_groups(session, company)
    schemes = await make_group(session, company, "Government Schemes", None, nature="ASSET")
    session.add(
        CompanySetting(
            company_id=company.company_id,
            setting_key="classification.expense_groups",
            setting_value=[
                {"type": "PREDEFINED", "reserved_name": "Direct Expenses"},
                {"type": "COMPANY_GROUP", "tally_guid": schemes.tally_guid},
            ],
            data_type="JSON",
        )
    )
    await session.flush()
    resolved = (
        await session.scalars(
            RESOLVE, {"c": company.company_id, "k": "classification.expense_groups"}
        )
    ).all()
    assert schemes.group_id in resolved and len(resolved) == 2


async def test_feature_flag_is_boolean_only(session: AsyncSession) -> None:
    company = await make_company(session)
    async with db_error(session, "enabled"):
        await session.execute(
            text("INSERT INTO feature_config VALUES (:c, 'X', NULL)"),
            {"c": company.company_id},
        )


async def test_setting_data_type_is_checked(session: AsyncSession) -> None:
    company = await make_company(session)
    async with db_error(session, "ck_company_settings_data_type"):
        session.add(
            CompanySetting(
                company_id=company.company_id,
                setting_key="analytics.top_n_default",
                setting_value=10,
                data_type="NUMBER",
            )
        )
        await session.flush()


@pytest.mark.req("SEC-1.13")
@pytest.mark.parametrize(
    "statement", ["UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"]
)
async def test_app_role_cannot_change_audit_logs(session: AsyncSession, statement: str) -> None:
    session.add(AuditLog(action="LOGIN", entity_type="USER", result="SUCCESS"))
    await session.flush()
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1
    async with db_error(session, "permission denied"):
        await session.execute(text(statement))


@pytest.mark.req("SEC-1.13")
@pytest.mark.parametrize(
    "statement", ["UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"]
)
def test_even_the_owner_cannot_change_audit_logs(statement: str) -> None:
    """The trigger holds even for a role with the privilege (defence in depth)."""
    url = make_url(get_settings().database_migration_url or "").set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as owner:
        owner.execute(
            "INSERT INTO audit_logs (action, entity_type, result) VALUES ('LOGIN', 'USER', 'OK')"
        )
        with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
            owner.execute(statement)
        owner.rollback()


async def test_one_flag_per_voucher_and_rule(session: AsyncSession) -> None:
    company = await make_company(session)
    groups = await make_predefined_groups(session, company)
    await make_ledger(session, company, "Customer A", groups["Sundry Debtors"])
    await make_ledger(session, company, "Sales", groups["Sales Accounts"])
    voucher = await make_voucher(
        session, company, await make_voucher_type(session, company, "Sales"), date(2024, 5, 1)
    )
    insert = text(
        "INSERT INTO anomaly_flags (company_id, voucher_id, rule_triggered, explanation_status) "
        "VALUES (:c, :v, 'LARGE_TRANSACTION', 'PENDING')"
    )
    params = {"c": company.company_id, "v": voucher.voucher_id}
    await session.execute(insert, params)
    async with db_error(session, "uq_anomaly_flags_voucher_id_rule_triggered"):
        await session.execute(insert, params)
