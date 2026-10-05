"""P15.1: the anomaly schema's new constraints, and the read-only role's row-level security.

The RLS part runs on REAL connections — one as `tally_app` (the application) and one as
`tally_readonly` (what the MCP server will use). The rollback `session` fixture cannot prove it:
everything there runs on one connection as one role.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.config import AnomalyFlag, AnomalyScanState
from app.models.enums import AnomalyRule, ExplanationStatus, ExplanationUnavailableReason
from tests.analytics.books import Books, make_books

Factory = async_sessionmaker[AsyncSession]


async def a_voucher(books: Books, day: date = date(2025, 5, 2)) -> uuid.UUID:
    voucher = await books.voucher(
        "Sales", day, [("Customer A", "DEBIT", "450000"), ("Sales", "CREDIT", "450000")]
    )
    return voucher.voucher_id


def a_flag(books: Books, voucher_id: uuid.UUID, **kw: object) -> AnomalyFlag:
    return AnomalyFlag(
        **{
            "company_id": books.company.company_id,
            "voucher_id": voucher_id,
            "rule_triggered": AnomalyRule.UNUSUALLY_LARGE_SD,
            "transaction_amount": Decimal("450000"),
            "historical_average": Decimal("70000"),
            "historical_max": Decimal("120000"),
            "deviation_percent": Decimal("542.857143"),
            "explanation_status": ExplanationStatus.PENDING,
            **kw,
        }
    )


# --- the constraints the migration adds -----------------------------------------------------


@pytest.mark.req("FR-3.4")
async def test_a_flag_stores_every_piece_of_evidence(session: AsyncSession) -> None:
    books = await make_books(session)
    session.add(a_flag(books, await a_voucher(books)))
    await session.flush()
    found = (await session.execute(select(AnomalyFlag))).scalar_one()
    assert found.transaction_amount == Decimal("450000")
    assert found.historical_average == Decimal("70000")
    assert found.historical_max == Decimal("120000")
    assert found.deviation_percent == Decimal("542.857143")
    assert found.rule_triggered == AnomalyRule.UNUSUALLY_LARGE_SD
    # The P15 additions all default to "nothing has happened yet".
    assert found.explanation_attempts == 0
    assert found.explanation_last_attempt_at is None
    assert found.explanation_unavailable_reason is None
    assert found.cleared_at is None


async def test_an_unknown_rule_name_is_refused(session: AsyncSession) -> None:
    # Free text until P15 (D-032); a typo would have created a rule nobody queries.
    books = await make_books(session)
    session.add(a_flag(books, await a_voucher(books), rule_triggered="UNUSUALY_LARGE"))
    with pytest.raises(IntegrityError, match="rule_triggered"):
        await session.flush()


async def test_an_unknown_unavailable_reason_is_refused(session: AsyncSession) -> None:
    books = await make_books(session)
    session.add(
        a_flag(
            books,
            await a_voucher(books),
            explanation_status=ExplanationStatus.UNAVAILABLE,
            explanation_unavailable_reason="BECAUSE",
        )
    )
    with pytest.raises(IntegrityError, match="explanation_unavailable_reason"):
        await session.flush()


@pytest.mark.parametrize("reason", [r.value for r in ExplanationUnavailableReason])
async def test_every_reason_the_enum_names_is_storable(session: AsyncSession, reason: str) -> None:
    books = await make_books(session)
    session.add(
        a_flag(
            books,
            await a_voucher(books),
            explanation_status=ExplanationStatus.UNAVAILABLE,
            explanation_unavailable_reason=reason,
        )
    )
    await session.flush()


async def test_the_company_index_the_list_endpoint_needs_exists(session: AsyncSession) -> None:
    found = await session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'anomaly_flags' AND indexdef LIKE '%company_id%'"
        )
    )
    defs = [row[0] for row in found]
    assert any("flagged_at" in d for d in defs), defs


async def test_the_scan_cursor_is_our_write_time_not_an_alter_id(session: AsyncSession) -> None:
    """D-055 #9. If this ever becomes an alter id again, a record held back by D-039 #7 would be
    skipped forever, so the column's name and type are worth pinning."""
    books = await make_books(session)
    session.add(
        AnomalyScanState(
            company_id=books.company.company_id, synced_through=datetime(2026, 3, 16, tzinfo=UTC)
        )
    )
    await session.flush()
    state = (await session.execute(select(AnomalyScanState))).scalar_one()
    assert state.synced_through == datetime(2026, 3, 16, tzinfo=UTC)
    assert not hasattr(state, "last_alter_id")


# --- row-level security for the read-only role (D-055 #5) -----------------------------------


@pytest.fixture
async def readonly() -> AsyncIterator[Factory]:
    """Sessions as `tally_readonly`, the role the MCP server will use."""
    dsn = get_settings().anomaly_readonly_database_url or ""
    # Point it at the test database, changing only the database - a plain string replace would
    # also rewrite the user name (`tally_readonly` -> `tally_test_readonly`).
    url = make_url(dsn.replace("postgresql://", "postgresql+asyncpg://")).set(
        database=make_url(get_settings().database_url or "").database
    )
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _two_companies(committed: Factory) -> tuple[Books, Books, int, int]:
    """One anomaly each, really committed, so another connection can see them."""
    async with committed() as s:
        mine = await make_books(s, name="Mine")
        theirs = await make_books(s, name="Theirs")
        ids = []
        for books in (mine, theirs):
            flag = a_flag(books, await a_voucher(books))
            s.add(flag)
            await s.flush()
            ids.append(flag.id)
        await s.commit()
    return mine, theirs, ids[0], ids[1]


@pytest.mark.req("SEC-1.12")
async def test_the_readonly_role_sees_only_the_company_set_at_spawn(
    committed: Factory, readonly: Factory
) -> None:
    mine, _theirs, my_flag, their_flag = await _two_companies(committed)
    async with readonly() as s:
        # SET takes no bind parameter; set_config does, which is how the MCP server will do it.
        await s.execute(
            text("SELECT set_config('app.company_id', :c, false)"),
            {"c": str(mine.company.company_id)},
        )
        ids = set((await s.execute(select(AnomalyFlag.id))).scalars())
    assert ids == {my_flag}, "the other company's evidence must not be reachable"
    assert their_flag not in ids


async def test_the_readonly_role_sees_nothing_when_no_company_is_set(
    committed: Factory, readonly: Factory
) -> None:
    """Fails closed: current_setting(..., true) is NULL when unset, so the policy matches no row."""
    await _two_companies(committed)
    async with readonly() as s:
        assert (await s.execute(select(AnomalyFlag.id))).scalars().all() == []


async def test_the_readonly_role_cannot_write_anything(
    committed: Factory, readonly: Factory
) -> None:
    """It has SELECT on anomaly_flags and no INSERT anywhere: the explainer writes ai_tool_log,
    not the server (the owner's correction to D-055 #5)."""
    mine, _theirs, _my_flag, _their_flag = await _two_companies(committed)
    async with readonly() as s:
        # SET takes no bind parameter; set_config does, which is how the MCP server will do it.
        await s.execute(
            text("SELECT set_config('app.company_id', :c, false)"),
            {"c": str(mine.company.company_id)},
        )
        for statement in (
            "UPDATE anomaly_flags SET reviewed = true",
            "DELETE FROM anomaly_flags",
            "INSERT INTO ai_tool_log (company_id, tool_name, status) VALUES "
            "('00000000-0000-0000-0000-000000000000', 'x', 'SUCCESS')",
        ):
            with pytest.raises(DBAPIError):
                await s.execute(text(statement))
            await s.rollback()


async def test_the_readonly_role_cannot_read_any_other_table(
    committed: Factory, readonly: Factory
) -> None:
    """The point of a separate role: vouchers, ledgers and audit logs are out of reach, so the
    MCP server could not return bulk data even if asked to (FR-3.5)."""
    await _two_companies(committed)
    async with readonly() as s:
        for table in ("vouchers", "voucher_entries", "ledgers", "audit_logs", "companies"):
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
            await s.rollback()


async def test_the_application_itself_still_sees_every_row(committed: Factory) -> None:
    """Enabling RLS applies it to every role but the owner, so without the tally_app policy the
    application would have seen no anomalies at all."""
    _mine, _theirs, my_flag, their_flag = await _two_companies(committed)
    async with committed() as s:
        ids = set((await s.execute(select(AnomalyFlag.id))).scalars())
    assert {my_flag, their_flag} <= ids
