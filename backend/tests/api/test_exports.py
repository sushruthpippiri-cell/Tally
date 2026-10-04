"""The export endpoint (EXP-1.1-1.6, SEC-1.11, LOG-1.1, AC-39, AC-61).

These tests run on REALLY committing connections, not the rollback `session` fixture: an export
reads through `app.core.db.snapshot()`, its own session on its own connection, so it can only
see data that has actually been committed - exactly as in production.
"""

import csv as _csv
import subprocess
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import exports
from app.core import db as core_db
from app.core.permissions import CompanyContext
from app.exports import reports
from app.exports.reports import ExportParams
from app.main import create_app
from app.models.company import User
from app.models.config import AuditLog, CustomFieldMapping
from app.models.enums import RoleName
from app.models.vouchers import Voucher
from tests.analytics.books import Books, make_books
from tests.factories import auth_header, make_user, make_voucher

Factory = async_sessionmaker[AsyncSession]
FROM, TO = date(2025, 4, 1), date(2026, 3, 31)
RANGE = {"from": FROM.isoformat(), "to": TO.isoformat()}


@pytest.fixture(autouse=True)
async def fresh_engine() -> AsyncIterator[None]:
    """The app's engine is cached for the whole process and its pool binds to the loop that
    first used it, while every test runs on its own loop. Every test here uses that engine (an
    export reads through `snapshot()`, not the rollback `session` fixture), so it is rebuilt for
    this test and disposed afterwards - otherwise the next test inherits connections belonging
    to a closed loop."""
    core_db.get_engine.cache_clear()
    core_db.session_factory.cache_clear()
    try:
        yield
    finally:
        await core_db.get_engine().dispose()
        core_db.get_engine.cache_clear()
        core_db.session_factory.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """The real app with no session override: every request opens its own connection, as in
    production, so `snapshot()` can only see committed data."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        yield api


async def _books(committed: Factory, sales: int = 4) -> tuple[Books, User, User]:
    async with committed() as s:
        books = await make_books(s, name="Sharma Trading Co.")
        for ledger in ("Customer A", "Customer B", "Cash", "HDFC Bank", "Supplier S"):
            await books.opening(ledger, "DEBIT", "0")
        for i in range(sales):
            await books.voucher(
                "Sales",
                date(2025, 5, 1) + timedelta(days=i),
                [("Customer A", "DEBIT", "100"), ("Sales", "CREDIT", "100")],
                number=f"S-{i}",
                items=[("Soap", "1", "100", "100")],
            )
        owner = await make_user(s, books.company, RoleName.OWNER)
        outsider = await make_user(s)  # no role in this company
        await s.commit()
    return books, owner, outsider


def url(books: Books, report: str) -> str:
    return f"/companies/{books.company.company_id}/exports/{report}"


def parse(text: str) -> list[list[str]]:
    return list(_csv.reader(text.lstrip("﻿").splitlines()))


def summary_of(text: str, label: str) -> Decimal:
    for row in parse(text):
        if row and row[0] == label and len(row) > 1 and row[1]:
            return Decimal(row[1])
    raise AssertionError(f"no summary line {label!r} in\n{text[:800]}")


def detail_sum(text: str, column: str = "Amount") -> Decimal:
    rows = parse(text)
    head = next(i for i, r in enumerate(rows) if column in r)
    index = rows[head].index(column)
    return sum(
        (Decimal(r[index]) for r in rows[head + 1 :] if len(r) > index and r[index]),
        Decimal(0),
    )


@pytest.mark.req("EXP-1.1")
async def test_a_csv_export_downloads_with_its_report_and_range_in_the_name(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    books, owner, _ = await _books(committed)
    r = await client.get(url(books, "sales"), params=RANGE, headers=auth_header(owner))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == (
        'attachment; filename="sales-2025-04-01-to-2026-03-31.csv"'
    )
    assert r.text.startswith("﻿")
    assert summary_of(r.text, "Total Sales Revenue") == Decimal("400.00")


async def test_a_pdf_export_downloads_as_a_pdf(
    client: httpx.AsyncClient, committed: Factory, tmp_path: Path
) -> None:
    books, owner, _ = await _books(committed)
    r = await client.get(
        url(books, "sales"), params={**RANGE, "format": "pdf"}, headers=auth_header(owner)
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].endswith('.pdf"')
    assert r.content.startswith(b"%PDF-")
    file = tmp_path / "out.pdf"
    file.write_bytes(r.content)
    text = subprocess.run(
        ["pdftotext", "-layout", str(file), "-"], capture_output=True, check=True
    ).stdout.decode()
    assert "₹400.00" in text


@pytest.mark.req("AC-39")
@pytest.mark.parametrize("report", ["sales", "purchases", "expenses", "receivables", "cash-flow"])
async def test_screen_drilldown_csv_and_pdf_show_the_same_figure(
    client: httpx.AsyncClient, committed: Factory, tmp_path: Path, report: str
) -> None:
    """AC-39: for the same filters, the dashboard figure, the drill-down total, the CSV summary
    and the text of the PDF are one and the same number."""
    books, owner, _ = await _books(committed)
    head = auth_header(owner)
    base = f"/companies/{books.company.company_id}/analytics/{report}"
    screen = (await client.get(base, params=RANGE, headers=head)).json()
    drill = (await client.get(f"{base}/drilldown", params=RANGE, headers=head)).json()
    figure = Decimal(screen["summary"]["amount"])
    assert Decimal(drill["total"]) == figure

    text = (await client.get(url(books, report), params=RANGE, headers=head)).text
    title = parse(text)[0][1]
    assert summary_of(text, title) == figure

    pdf = (
        await client.get(url(books, report), params={**RANGE, "format": "pdf"}, headers=head)
    ).content
    file = tmp_path / f"{report}.pdf"
    file.write_bytes(pdf)
    printed = subprocess.run(
        ["pdftotext", "-layout", str(file), "-"], capture_output=True, check=True
    ).stdout.decode()
    from app.exports.money import format_money

    direction = screen["summary"]["direction"]
    shown = format_money(figure)
    assert (f"{shown} {direction}" if direction else shown) in printed


@pytest.mark.req("EXP-1.6")
@pytest.mark.req("SEC-1.11")
async def test_a_user_without_access_to_the_company_gets_no_file(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    books, _, outsider = await _books(committed)
    r = await client.get(url(books, "sales"), params=RANGE, headers=auth_header(outsider))
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"
    # Nothing of the company's data leaks into the body.
    assert "Sharma" not in r.text


@pytest.mark.req("SEC-1.11")
async def test_another_companys_id_in_the_path_is_refused(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    books, owner, _ = await _books(committed)
    other = uuid.uuid4()
    r = await client.get(
        f"/companies/{other}/exports/sales", params=RANGE, headers=auth_header(owner)
    )
    assert r.status_code == 403


@pytest.mark.req("LOG-1.1")
async def test_an_export_is_audited_with_the_range_it_took(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    books, owner, _ = await _books(committed)
    customer = books.ledgers["Customer A"].ledger_id
    r = await client.get(
        url(books, "customer-revenue"),
        params={**RANGE, "customer": str(customer)},
        headers=auth_header(owner),
    )
    assert r.status_code == 200
    async with committed() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.company_id == books.company.company_id, AuditLog.action == "EXPORT"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == owner.user_id
    assert row.entity_type == "report" and row.entity_id == "customer-revenue"
    assert row.data_range == {
        "report": "customer-revenue",
        "format": "csv",
        "from": "2025-04-01",
        "to": "2026-03-31",
        "filters": {"customer": str(customer)},
    }


async def test_a_refused_export_is_not_audited(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    books, _, outsider = await _books(committed)
    await client.get(url(books, "sales"), params=RANGE, headers=auth_header(outsider))
    async with committed() as s:
        found = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "EXPORT"))).scalars().all()
        )
    assert found == []


async def test_the_default_range_is_the_financial_year_to_date_and_is_what_the_file_says(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    books, owner, _ = await _books(committed)
    r = await client.get(url(books, "sales"), headers=auth_header(owner))
    assert r.status_code == 200
    # The name of the file, the audit row and the header block agree.
    async with committed() as s:
        ctx = CompanyContext(books.company.company_id, owner.user_id, frozenset())
        covers = await reports.effective_range(s, ctx, ExportParams())
    expected = f"{covers[0].isoformat()} to {covers[1].isoformat()}"
    assert expected.replace(" to ", "-to-") in r.headers["content-disposition"]
    assert ["Date range", expected] in parse(r.text)


@pytest.mark.parametrize(
    ("report", "params", "status"),
    [
        ("not-a-report", {}, 422),
        ("sales", {"format": "xlsx"}, 422),
        ("sales", {"from": "2026-03-31", "to": "2025-04-01"}, 422),
        ("stock", {"period_days": "45"}, 422),
    ],
)
async def test_a_bad_request_is_refused_before_anything_is_produced(
    client: httpx.AsyncClient,
    committed: Factory,
    report: str,
    params: dict[str, str],
    status: int,
) -> None:
    books, owner, _ = await _books(committed)
    r = await client.get(url(books, report), params=params, headers=auth_header(owner))
    assert r.status_code == status, r.text


@pytest.mark.req("AC-61")
async def test_a_mapped_custom_field_reaches_the_export_without_changing_a_total(
    client: httpx.AsyncClient, committed: Factory, tmp_path: Path
) -> None:
    books, owner, _ = await _books(committed)
    head = auth_header(owner)
    base = f"/companies/{books.company.company_id}/analytics/sales"

    def total() -> Decimal:
        return Decimal(screen["summary"]["amount"])

    screen = (await client.get(base, params=RANGE, headers=head)).json()
    before = total()

    async with committed() as s:
        s.add(
            CustomFieldMapping(
                company_id=books.company.company_id,
                collection_type="VOUCHER",
                tally_field="UDFSalesman",
                field_key="salesman",
                data_type="TEXT",
                is_active=True,
            )
        )
        voucher = (
            (
                await s.execute(
                    select(Voucher)
                    .where(Voucher.company_id == books.company.company_id)
                    .order_by(Voucher.voucher_date)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        assert voucher is not None
        voucher.custom_fields = {"salesman": "R. Nair"}
        await s.commit()

    screen = (await client.get(base, params=RANGE, headers=head)).json()
    assert total() == before  # a custom field is shown, never summed (DR-UDF-2)

    drill = (await client.get(f"{base}/drilldown", params=RANGE, headers=head)).json()
    assert any((r["custom_fields"] or {}).get("salesman") == "R. Nair" for r in drill["rows"])

    text = (await client.get(url(books, "sales"), params=RANGE, headers=head)).text
    assert "Salesman" in parse(text)[0] or any("Salesman" in r for r in parse(text))
    assert "R. Nair" in text
    assert summary_of(text, "Total Sales Revenue") == before

    pdf = (
        await client.get(url(books, "sales"), params={**RANGE, "format": "pdf"}, headers=head)
    ).content
    file = tmp_path / "udf.pdf"
    file.write_bytes(pdf)
    printed = subprocess.run(
        ["pdftotext", "-layout", str(file), "-"], capture_output=True, check=True
    ).stdout.decode()
    assert "R. Nair" in printed


# --- one snapshot per export (D-054, the owner's correction) ------------------------------
#
# These drive `exports._csv` directly rather than over HTTP. The ASGI transport and Starlette's
# middleware buffer a StreamingResponse, so by the time the client sees its first byte the whole
# export has already run - an HTTP-level test could not place a commit *between* two of the
# export's reads, which is the whole point. The property belongs to the generator, so that is
# where it is proven.


async def _late_sale(committed: Factory, books: Books, number: str) -> None:
    """A sync landing while a download is in flight, on its own connection, really committed."""
    async with committed() as s:
        await make_voucher(
            s,
            books.company,
            books.types["Sales"],
            date(2025, 6, 1),
            [("Customer A", "DEBIT", "9999"), ("Sales", "CREDIT", "9999")],
            number=number,
        )
        await s.commit()


async def _download_with_a_sync_midway(
    committed: Factory, books: Books, owner: User, number: str
) -> str:
    """Read the export's first chunk, let a sync commit, then read the rest."""
    ctx = CompanyContext(books.company.company_id, owner.user_id, frozenset({RoleName.OWNER}))
    params = ExportParams(date_from=FROM, date_to=TO)
    reports.PAGE, original = 2, reports.PAGE
    try:
        stream = exports._csv(ctx, "sales", params)
        chunks = [await anext(stream)]  # the summary has been read by now
        await _late_sale(committed, books, number)
        async for chunk in stream:
            chunks.append(chunk)
    finally:
        reports.PAGE = original
    return "".join(chunks)


@pytest.mark.req("AC-39")
async def test_a_sync_committing_mid_download_cannot_break_the_file(
    client: httpx.AsyncClient, committed: Factory
) -> None:
    """A streamed export asks several questions - the summary, then page after page of rows -
    and promises the rows add up to the summary. Every read shares one REPEATABLE READ
    snapshot, so a sync committing between those statements cannot get in (D-054)."""
    books, owner, _ = await _books(committed, sales=6)
    text = await _download_with_a_sync_midway(committed, books, owner, "LATE-1")
    assert summary_of(text, "Total Sales Revenue") == Decimal("600.00")
    assert detail_sum(text) == Decimal("600.00")
    assert "LATE-1" not in text  # the late voucher belongs to the next export, not this one
    # And it really was committed: the next export, on a new snapshot, sees it.
    later = await client.get(url(books, "sales"), params=RANGE, headers=auth_header(owner))
    assert summary_of(later.text, "Total Sales Revenue") == Decimal("10599.00")
    assert "LATE-1" in later.text


@pytest.mark.req("AC-39")
async def test_under_read_committed_the_same_download_would_not_add_up(
    client: httpx.AsyncClient, committed: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mutation check: with the snapshot removed, the very same sequence produces a file
    whose rows no longer match its own summary - which is what AC-39 forbids."""

    @asynccontextmanager
    async def read_committed() -> AsyncIterator[AsyncSession]:
        async with core_db.session_factory()() as session:
            try:
                yield session
            finally:
                await session.rollback()

    monkeypatch.setattr(exports, "snapshot", read_committed)
    books, owner, _ = await _books(committed, sales=6)
    text = await _download_with_a_sync_midway(committed, books, owner, "LATE-2")
    assert summary_of(text, "Total Sales Revenue") == Decimal("600.00")
    assert detail_sum(text) != Decimal("600.00"), "READ COMMITTED should have let the sync in"
    assert "LATE-2" in text


async def test_an_export_cannot_write(client: httpx.AsyncClient, committed: Factory) -> None:
    """The snapshot is READ ONLY as well, so a write slipped into an export is refused by
    PostgreSQL rather than landing quietly."""
    await _books(committed)
    async with core_db.snapshot() as session:
        with pytest.raises(DBAPIError, match="read-only"):
            await session.execute(text("UPDATE companies SET name = 'x' WHERE true"))


async def test_a_client_that_disconnects_mid_download_releases_its_session(
    committed: Factory,
) -> None:
    """`_started` closes the stream in its `finally`, so an abandoned download does not hold a
    snapshot (and therefore a connection) open."""
    books, owner, _ = await _books(committed, sales=6)
    ctx = CompanyContext(books.company.company_id, owner.user_id, frozenset({RoleName.OWNER}))
    reports.PAGE, original = 2, reports.PAGE
    try:
        body = await exports._started(exports._csv(ctx, "sales", ExportParams(FROM, TO)))
        assert await anext(body)
        await body.aclose()  # the client went away
    finally:
        reports.PAGE = original
    # The engine's pool is back to idle: nothing is still checked out.
    assert core_db.get_engine().pool.checkedout() == 0
