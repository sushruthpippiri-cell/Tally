"""The CSV renderer (EXP-1.1, D-053 #6). No database: the figures are given, and the point is
how they are written for Excel."""

from decimal import Decimal

import pytest

from app.exports.report import Column, Report, SummaryLine
from tests.exports.conftest import parse, rows_of, table, to_csv

HEADINGS = ["Date", "Ledger", "Amount"]


def a_report(**kw: object) -> Report:
    base: dict[str, object] = {
        "title": "Total Sales Revenue",
        "company_name": "Sharma Trading Co.",
        "company_timezone": "Asia/Kolkata",
        "meta": [("Date range", "2025-04-01 to 2026-03-31")],
        "summary": [SummaryLine("Total Sales Revenue", Decimal("100.00"))],
        "columns": [
            Column("voucher_date", "Date", "date"),
            Column("ledger_name", "Ledger"),
            Column("amount", "Amount", "amount"),
        ],
        "rows": rows_of([]),
        "total_rows": 0,
    }
    return Report(**(base | kw))  # type: ignore[arg-type]


@pytest.mark.req("EXP-1.1")
async def test_the_header_block_names_the_report_company_range_and_time() -> None:
    text = await to_csv(
        a_report(
            meta=[
                ("Date range", "2025-04-01 to 2026-03-31"),
                ("Filter: Customer", "Customer A"),
                ("Generated", "04 Oct 2026, 19:40 (Asia/Kolkata)"),
            ]
        )
    )
    rows = parse(text)
    assert rows[0] == ["Report", "Total Sales Revenue"]
    assert rows[1] == ["Company", "Sharma Trading Co."]
    assert ["Date range", "2025-04-01 to 2026-03-31"] in rows
    assert ["Filter: Customer", "Customer A"] in rows
    assert ["Generated", "04 Oct 2026, 19:40 (Asia/Kolkata)"] in rows


async def test_excel_sees_the_file_as_utf_8() -> None:
    text = await to_csv(a_report(company_name="शर्मा ट्रेडिंग"))
    assert text.startswith("﻿")  # without the BOM Excel reads it as cp1252
    assert "शर्मा ट्रेडिंग" in text


@pytest.mark.req("EXP-1.4")
async def test_a_sales_export_shows_its_three_figures_on_separate_lines() -> None:
    text = await to_csv(
        a_report(
            summary=[
                SummaryLine("Total Sales Revenue", Decimal("100.00")),
                SummaryLine("Product-attributed Revenue", Decimal("90.00")),
                SummaryLine("Product Attribution Difference", Decimal("10.00")),
            ]
        )
    )
    rows = parse(text)
    assert ["Total Sales Revenue", "100.00", "", ""] in rows
    assert ["Product-attributed Revenue", "90.00", "", ""] in rows
    assert ["Product Attribution Difference", "10.00", "", ""] in rows


async def test_detail_rows_add_up_to_the_summary_line() -> None:
    text = await to_csv(
        a_report(
            summary=[SummaryLine("Total Sales Revenue", Decimal("100.00"))],
            rows=rows_of(
                [
                    {"voucher_date": "2025-05-01", "ledger_name": "Sales", "amount": Decimal("60")},
                    {"voucher_date": "2025-06-01", "ledger_name": "Sales", "amount": Decimal("40")},
                ]
            ),
            total_rows=2,
        )
    )
    detail = table(text, HEADINGS)
    assert sum(Decimal(r["Amount"]) for r in detail) == Decimal("100.00")


async def test_an_amount_is_a_number_never_quoted_or_prefixed() -> None:
    text = await to_csv(
        a_report(
            rows=rows_of(
                [{"voucher_date": "2025-05-01", "ledger_name": "S", "amount": Decimal("-2500.5")}]
            ),
            total_rows=1,
        )
    )
    # A leading "'" or a quote would make Excel treat the cell as text and refuse to sum it.
    assert ",-2500.50\r\n" in text


@pytest.mark.req("EXP-1.1")
async def test_a_tally_name_that_looks_like_a_formula_is_defused() -> None:
    # Ledger and item names come from the customer's Tally, not from us (D-053 #6).
    names = ["=cmd|' /c calc'!A1", "+1+1", "-2+3", "@SUM(A1)", "\tTabbed", "Normal Ledger"]
    text = await to_csv(
        a_report(
            rows=rows_of(
                [
                    {"voucher_date": "2025-05-01", "ledger_name": n, "amount": Decimal("1")}
                    for n in names
                ]
            ),
            total_rows=len(names),
        )
    )
    written = [r["Ledger"] for r in table(text, HEADINGS)]
    assert written == [f"'{n}" for n in names[:-1]] + ["Normal Ledger"]


@pytest.mark.req("ACC-9.6")
async def test_an_unavailable_balance_is_empty_never_zero() -> None:
    text = await to_csv(
        a_report(
            title="Receivables",
            summary=[
                SummaryLine("Receivables", None, note="opening balance unavailable for 2 ledger(s)")
            ],
            columns=[
                Column("ledger_name", "Ledger"),
                Column("amount", "Amount (Dr +)", "signed_amount"),
                Column("direction", "Dr/Cr"),
            ],
            rows=rows_of([{"ledger_name": "Customer A", "amount": None, "direction": ""}]),
            total_rows=1,
        )
    )
    rows = parse(text)
    assert ["Receivables", "", "", "opening balance unavailable for 2 ledger(s)"] in rows
    assert ["Customer A", "", ""] in rows
    assert "0.00" not in text


async def test_a_note_is_always_written_out() -> None:
    text = await to_csv(a_report(notes=["Journals are included in net cash flow."]))
    assert ["Note", "Journals are included in net cash flow."] in parse(text)


async def test_quantities_keep_their_own_form() -> None:
    text = await to_csv(
        a_report(
            columns=[Column("quantity", "Quantity", "quantity"), Column("unit", "Unit")],
            rows=rows_of([{"quantity": Decimal("400.000000"), "unit": "Nos"}]),
            total_rows=1,
        )
    )
    assert ["400", "Nos"] in parse(text)
