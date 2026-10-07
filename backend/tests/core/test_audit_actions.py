"""P16.3: every audited action is classified against LOG-1.1 (SRS 15).

`audit.record` takes a free-form string, so until now a new audited event could be added under
any name and nothing said which LOG-1.1 clause it answered - or noticed when a clause had
nothing answering it at all. ACTIONS is that mapping, and `record` refuses anything outside it.

The forward direction - no unregistered action is ever written - is enforced at runtime by
`record` itself, across the whole suite: every audited path has a test, so an action missing
from ACTIONS fails the moment that path runs. It earned its keep immediately, catching
USER_ATTACHED and the two resolution-change actions that a source scan had missed.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app
from app.core import audit
from app.core.errors import AppError
from app.models.config import AuditLog
from tests.factories import make_company

APP = Path(app.__file__).parent

# LOG-1.1, clause for clause. The SRS wording is the key, so a clause cannot quietly vanish.
LOG_1_1_CLAUSES = (
    "login",
    "sync requests",
    "schedule changes",
    "Agent registration/rotation/revocation",
    "setting and feature-flag changes",
    "user and role changes",
    "anomaly reviews",
    "exports",
    "system changes to vouchers and masters",
)


@pytest.mark.req("LOG-1.1")
def test_every_log_1_1_clause_has_at_least_one_action() -> None:
    for clause in LOG_1_1_CLAUSES:
        assert audit.ACTIONS.get(clause), f"LOG-1.1 clause {clause!r} has no audited action"


def test_no_action_belongs_to_two_clauses() -> None:
    seen: dict[str, str] = {}
    for clause, actions in audit.ACTIONS.items():
        for action in actions:
            assert action not in seen, f"{action} is in both {seen[action]!r} and {clause!r}"
            seen[action] = clause


@pytest.mark.req("LOG-1.1")
def test_the_registry_has_nothing_the_source_never_writes() -> None:
    """A stale entry would make a LOG-1.1 clause look answered when nothing writes it.

    A plain substring search, not an AST walk: actions reach `record` in three shapes - inline
    as `action="X"`, assigned first (app/sync/vouchers.py picks between two with a conditional),
    and passed positionally (app/sync/hierarchy.py's `_audit_change`). An AST scan has to know
    all three and silently misses the next one; the literal has to be in the source either way.
    """
    source = "\n".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py"))
    never_written = {action for action in audit.KNOWN_ACTIONS if f'"{action}"' not in source}
    assert never_written == set(), f"in audit.ACTIONS but never written: {sorted(never_written)}"


async def test_an_unregistered_action_is_refused(session: AsyncSession) -> None:
    company = await make_company(session)
    with pytest.raises(AppError, match="Unregistered audit action"):
        await audit.record(
            session,
            company_id=company.company_id,
            user_id=None,
            action="SOMETHING_NEW",
            entity_type="voucher",
        )
    rows = await session.execute(select(AuditLog).where(AuditLog.action == "SOMETHING_NEW"))
    assert rows.first() is None


@pytest.mark.req("LOG-1.2")
async def test_a_registered_action_records_every_log_1_2_field(session: AsyncSession) -> None:
    company = await make_company(session)
    entity = uuid.uuid4()
    await audit.record(
        session,
        company_id=company.company_id,
        user_id=None,  # "system"
        action="VOUCHER_MODIFIED",
        entity_type="voucher",
        entity_id=str(entity),
        before={"amount": "100.00"},
        after={"amount": "150.00"},
        data_range={"from": "2026-04-01", "to": "2026-04-30"},
        result="SUCCESS",
    )
    row = (
        await session.execute(select(AuditLog).where(AuditLog.entity_id == str(entity)))
    ).scalar_one()
    assert row.user_id is None and row.company_id == company.company_id
    assert (row.action, row.entity_type, row.result) == ("VOUCHER_MODIFIED", "voucher", "SUCCESS")
    assert row.before_value == {"amount": "100.00"} and row.after_value == {"amount": "150.00"}
    assert row.data_range == {"from": "2026-04-01", "to": "2026-04-30"}
    assert row.created_at is not None
