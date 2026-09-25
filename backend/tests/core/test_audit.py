"""P2.7: audit service (SRS 15, LOG-1.2)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.config import AuditLog
from tests.factories import make_company, make_user


# The fields are proven here; that every LOG-1.1 action writes them: each action's own tests.
@pytest.mark.req_partial("LOG-1.2")
async def test_record_writes_every_log_1_2_field(session: AsyncSession) -> None:
    company = await make_company(session)
    user = await make_user(session, company)
    await audit.record(
        session,
        company_id=company.company_id,
        user_id=user.user_id,
        action="SETTING_CHANGED",
        entity_type="company_setting",
        entity_id="analytics.top_n_default",
        before={"value": 10},
        after={"value": 20},
        data_range={"from": "2024-04-01", "to": "2024-06-30"},
        result="SUCCESS",
    )
    row = (await session.execute(select(AuditLog))).scalar_one()
    assert (row.company_id, row.user_id, row.action, row.entity_type, row.entity_id) == (
        company.company_id,
        user.user_id,
        "SETTING_CHANGED",
        "company_setting",
        "analytics.top_n_default",
    )
    assert row.before_value == {"value": 10}
    assert row.after_value == {"value": 20}
    assert row.data_range == {"from": "2024-04-01", "to": "2024-06-30"}
    assert row.result == "SUCCESS"
    assert row.created_at is not None


async def test_system_actor_is_a_null_user(session: AsyncSession) -> None:
    await audit.record(
        session,
        company_id=None,
        user_id=None,
        action="VOUCHER_CANCELLED",
        entity_type="voucher",
        entity_id=str(uuid.uuid4()),
    )
    row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.user_id is None
    assert row.result == "SUCCESS"


def test_diff_keeps_only_changed_keys() -> None:
    before = {"a": 1, "b": 2, "c": 3}
    after = {"a": 1, "b": 5, "d": 4}
    assert audit.diff(before, after) == ({"b": 2, "c": 3}, {"b": 5, "d": 4})
    assert audit.diff({"a": 1}, {"a": 1}) == ({}, {})
