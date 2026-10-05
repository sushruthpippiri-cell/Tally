"""P15.3: the MCP server (FR-3.5, SEC-1.12, SRS 19.3, PERF-1.4).

The server is driven through a real MCP client over the real protocol — `mcp.Client` accepts an
`MCPServer` instance and connects to it in process, so these tests exercise the same `build()`
server the stdio subprocess runs, without spawning one per test.

The database connection is as `tally_readonly`, so the row-level security policy is in force and
"another company's anomaly" is refused by the database, not only by the query.
"""

import pathlib
import time
import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from mcp import Client
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.anomaly import mcp_server, redact
from app.core.config import get_settings
from app.models.config import AnomalyFlag
from app.models.enums import AnomalyRule, ExplanationStatus
from tests.analytics.books import Books, make_books

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def readonly_sessions() -> AsyncIterator[Factory]:
    """What the server itself uses: the read-only role, pointed at the test database."""
    dsn = get_settings().anomaly_readonly_database_url or ""
    url = make_url(mcp_server._async_url(dsn)).set(
        database=make_url(get_settings().database_url or "").database
    )
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _flag(books: Books, **kw: object) -> int:
    v = await books.voucher(
        "Sales",
        date(2025, 5, 2),
        [("Customer A", "DEBIT", "450000"), ("Sales", "CREDIT", "450000")],
    )
    flag = AnomalyFlag(
        **{
            "company_id": books.company.company_id,
            "voucher_id": v.voucher_id,
            "rule_triggered": AnomalyRule.UNUSUALLY_LARGE_SD,
            "transaction_amount": Decimal("450000"),
            "historical_average": Decimal("70000"),
            "historical_max": Decimal("120000"),
            "deviation_percent": Decimal("542.857143"),
            "explanation_status": ExplanationStatus.PENDING,
            **kw,
        }
    )
    books.session.add(flag)
    await books.session.flush()
    return flag.id


async def _two_companies(committed: Factory) -> tuple[uuid.UUID, int, uuid.UUID, int]:
    async with committed() as s:
        mine = await make_books(s, name="Mine")
        theirs = await make_books(s, name="Theirs")
        my_id = await _flag(mine)
        their_id = await _flag(theirs)
        await s.commit()
    return mine.company.company_id, my_id, theirs.company.company_id, their_id


@pytest.mark.req("SRS-19.3")
async def test_the_server_exposes_exactly_one_read_only_tool(
    committed: Factory, readonly_sessions: Factory
) -> None:
    company_id, _, _, _ = await _two_companies(committed)
    async with Client(mcp_server.build(readonly_sessions, company_id)) as client:
        tools = (await client.list_tools()).tools
    assert [t.name for t in tools] == [mcp_server.TOOL]
    assert tools[0].annotations is not None
    assert tools[0].annotations.read_only_hint is True
    # One parameter, the anomaly id: there is no way to ask for a range, a company or a query.
    assert set(tools[0].input_schema["properties"]) == {"anomaly_id"}


@pytest.mark.req("FR-3.5")
async def test_the_tool_returns_the_stored_evidence_for_one_anomaly(
    committed: Factory, readonly_sessions: Factory
) -> None:
    company_id, my_flag, _, _ = await _two_companies(committed)
    async with Client(mcp_server.build(readonly_sessions, company_id)) as client:
        result = await client.call_tool(mcp_server.TOOL, {"anomaly_id": my_flag})
    assert result.is_error is not True
    got = result.structured_content
    assert got is not None
    assert got["rule"] == AnomalyRule.UNUSUALLY_LARGE_SD
    assert got["transaction_amount"] == "450000.0000"
    assert got["historical_average"] == "70000.0000"
    assert got["historical_maximum"] == "120000.0000"
    assert got["deviation_percent"] == "542.857143"
    # Placeholders, never the real names (SEC-1.12, D-055 #6).
    assert got["party"] == redact.PARTY
    assert got["voucher"] == redact.VOUCHER
    assert set(got) <= set(redact.FIELDS), "the tool may return no field the disclosure omits"


@pytest.mark.req("SEC-1.12")
async def test_another_companys_anomaly_is_not_found(
    committed: Factory, readonly_sessions: Factory
) -> None:
    """The id exists — it simply belongs to someone else. Refused by the RLS policy, so a bug in
    the server's own WHERE could not leak it either (D-055 #5)."""
    company_id, _, _, their_flag = await _two_companies(committed)
    async with Client(mcp_server.build(readonly_sessions, company_id)) as client:
        result = await client.call_tool(mcp_server.TOOL, {"anomaly_id": their_flag})
    assert result.is_error is True
    assert mcp_server.NOT_FOUND in str(result.content)


async def test_the_policy_alone_refuses_another_company(
    committed: Factory, readonly_sessions: Factory
) -> None:
    """With the server's own company filter removed, the database still refuses: the guarantee
    does not rest on the query being right."""
    company_id, _, _, their_flag = await _two_companies(committed)
    async with readonly_sessions() as session:
        from sqlalchemy import select, text

        await session.execute(
            text("SELECT set_config('app.company_id', :c, false)"), {"c": str(company_id)}
        )
        # No company_id predicate at all - only the policy stands between us and their row.
        found = await session.execute(select(AnomalyFlag.id).where(AnomalyFlag.id == their_flag))
        assert found.scalar_one_or_none() is None


async def test_a_cleared_flag_is_not_explained(
    committed: Factory, readonly_sessions: Factory
) -> None:
    """A flag whose rule stopped triggering (D-055 #10) has nothing to explain."""
    from datetime import UTC, datetime

    async with committed() as s:
        books = await make_books(s, name="Mine")
        flag_id = await _flag(books, cleared_at=datetime(2026, 3, 16, tzinfo=UTC))
        company_id = books.company.company_id
        await s.commit()
    async with Client(mcp_server.build(readonly_sessions, company_id)) as client:
        result = await client.call_tool(mcp_server.TOOL, {"anomaly_id": flag_id})
    assert result.is_error is True


@pytest.mark.req("PERF-1.4")
async def test_the_evidence_call_is_well_under_two_seconds(
    committed: Factory, readonly_sessions: Factory
) -> None:
    company_id, my_flag, _, _ = await _two_companies(committed)
    async with Client(mcp_server.build(readonly_sessions, company_id)) as client:
        await client.call_tool(mcp_server.TOOL, {"anomaly_id": my_flag})  # connect + warm up
        started = time.monotonic()
        await client.call_tool(mcp_server.TOOL, {"anomaly_id": my_flag})
        took = time.monotonic() - started
    assert took < 2.0, took


async def test_no_placeholder_label_contains_a_digit() -> None:
    """D-055 #8. "Voucher 1" would have put 1 into every duplicate explanation, and the FR-3.6
    number check would have discarded it - destroying the explanations it exists to protect."""
    for label in (redact.PARTY, redact.VOUCHER, redact.OTHER_VOUCHER):
        assert not any(c.isdigit() for c in label), label


@pytest.mark.req("SRS-19.3")
async def test_the_stdio_subprocess_starts_with_credentials_only_in_its_environment(
    committed: Factory,
) -> None:
    """The production path: the explainer spawns `python -m app.anomaly.mcp_server`. Nothing
    sensitive goes on the command line, where `ps` would show it to every user on the machine
    (D-055 #5). In-process tests cover the logic; this one covers the entry point and the
    transport, so renaming an environment variable cannot pass unnoticed.
    """
    import os
    import sys

    from mcp import StdioServerParameters

    company_id, my_flag, _, _ = await _two_companies(committed)
    dsn = make_url(get_settings().anomaly_readonly_database_url or "").set(
        database=make_url(get_settings().database_url or "").database
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.anomaly.mcp_server"],
        env={
            "PATH": os.environ["PATH"],
            mcp_server.COMPANY_ENV: str(company_id),
            mcp_server.DSN_ENV: dsn.render_as_string(hide_password=False),
        },
        cwd=str(pathlib.Path(__file__).resolve().parents[2]),
    )
    async with Client(params) as client:
        assert [t.name for t in (await client.list_tools()).tools] == [mcp_server.TOOL]
        result = await client.call_tool(mcp_server.TOOL, {"anomaly_id": my_flag})
    assert result.is_error is not True
    assert result.structured_content is not None
    assert result.structured_content["party"] == redact.PARTY
