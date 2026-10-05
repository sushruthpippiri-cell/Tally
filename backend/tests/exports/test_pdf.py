"""PDF export (EXP-1.1, EXP-1.2; D-053 #7). The figures are read back out of the rendered file
with poppler's pdftotext, and the embedded faces with pdffonts, so these tests check the PDF a
reader actually gets - not the HTML on the way in."""

import asyncio
import re
import subprocess
import time
from decimal import Decimal
from pathlib import Path

import pytest

from app.exports import pdf as pdf_export
from app.exports.report import Bar, Chart, Column, Report, SummaryLine
from tests.exports.conftest import rows_of

DEVANAGARI = "शर्मा ट्रेडिंग"
TELUGU = "శర్మా ట్రేడింగ్"


def a_report(**kw: object) -> Report:
    base: dict[str, object] = {
        "title": "Total Sales Revenue",
        "company_name": "Sharma Trading Co.",
        "company_timezone": "Asia/Kolkata",
        "meta": [
            ("Date range", "2025-04-01 to 2026-03-31"),
            ("Generated", "04 Oct 2026, 19:40 (Asia/Kolkata)"),
        ],
        "summary": [SummaryLine("Total Sales Revenue", Decimal("1234567.89"))],
        "columns": [
            Column("voucher_date", "Date", "date"),
            Column("ledger_name", "Ledger"),
            Column("amount", "Amount", "amount"),
        ],
        "rows": rows_of([]),
        "total_rows": 0,
    }
    return Report(**(base | kw))  # type: ignore[arg-type]


def text_of(data: bytes, tmp_path: Path) -> str:
    file = tmp_path / "out.pdf"
    file.write_bytes(data)
    done = subprocess.run(["pdftotext", "-layout", str(file), "-"], capture_output=True, check=True)
    return done.stdout.decode("utf-8")


def fonts_of(data: bytes, tmp_path: Path) -> str:
    file = tmp_path / "fonts.pdf"
    file.write_bytes(data)
    done = subprocess.run(["pdffonts", str(file)], capture_output=True, check=True)
    return done.stdout.decode("utf-8")


@pytest.mark.req("EXP-1.1")
async def test_the_pdf_carries_the_title_company_range_and_figures(tmp_path: Path) -> None:
    data = await pdf_export.render(
        a_report(
            rows=rows_of(
                [
                    {
                        "voucher_date": "2025-05-02",
                        "ledger_name": "Sales",
                        "amount": Decimal("1234567.89"),
                    }
                ]
            ),
            total_rows=1,
        )
    )
    assert data.startswith(b"%PDF-")
    text = text_of(data, tmp_path)
    assert "Total Sales Revenue" in text
    assert "Sharma Trading Co." in text
    assert "2025-04-01 to 2026-03-31" in text
    assert "04 Oct 2026, 19:40 (Asia/Kolkata)" in text
    # The figure the owner reads is the backend's, formatted the way the screen formats it.
    assert "₹12,34,567.89" in text
    assert "Page 1 of 1" in text


@pytest.mark.req("EXP-1.2")
async def test_a_chart_is_drawn_from_the_same_series_with_every_figure_written_on_it(
    tmp_path: Path,
) -> None:
    chart = Chart(
        "Total Sales Revenue by month",
        [Bar("Apr 2025", Decimal("10000")), Bar("May 2025", Decimal("-2500.50"))],
    )
    text = text_of(await pdf_export.render(a_report(charts=[chart])), tmp_path)
    assert "Total Sales Revenue by month" in text
    assert "Apr 2025" in text and "May 2025" in text
    # No value axis: each bar carries its own exact amount (D-053 #5).
    assert "₹10,000.00" in text and "-₹2,500.50" in text


async def test_a_chart_with_nothing_to_show_is_left_out(tmp_path: Path) -> None:
    text = text_of(
        await pdf_export.render(a_report(charts=[Chart("Empty", [Bar("x", None)])])), tmp_path
    )
    assert "Empty" not in text


@pytest.mark.req("ACC-9.6")
async def test_an_unavailable_figure_reads_unavailable_not_zero(tmp_path: Path) -> None:
    text = text_of(
        await pdf_export.render(
            a_report(
                title="Receivables",
                summary=[SummaryLine("Receivables", None, note="2 ledgers have no opening")],
            )
        ),
        tmp_path,
    )
    assert "unavailable" in text
    assert "₹0.00" not in text


async def test_a_count_is_printed_as_a_number_not_as_money(tmp_path: Path) -> None:
    text = text_of(
        await pdf_export.render(
            a_report(summary=[SummaryLine("Dead stock", Decimal("7"), kind="integer")])
        ),
        tmp_path,
    )
    assert "Dead stock" in text and "₹7.00" not in text


@pytest.mark.req("D-053")
async def test_a_name_in_an_indian_script_renders_with_a_bundled_noto_face(
    tmp_path: Path,
) -> None:
    data = await pdf_export.render(
        a_report(
            company_name=DEVANAGARI,
            rows=rows_of(
                [{"voucher_date": "2025-05-02", "ledger_name": TELUGU, "amount": Decimal("1")}]
            ),
            total_rows=1,
        )
    )
    text = text_of(data, tmp_path)
    # The glyphs mapped: pdftotext gets the characters back, not boxes.
    assert DEVANAGARI.replace(" ", "") in text.replace(" ", "")
    assert TELUGU.replace(" ", "") in text.replace(" ", "")
    embedded = fonts_of(data, tmp_path)
    assert "Noto-Sans-Devanagari" in embedded, embedded
    assert "Noto-Sans-Telugu" in embedded, embedded
    # Every face is embedded (column "emb" = yes), so the file renders anywhere.
    assert " no " not in embedded


async def test_a_tally_name_cannot_inject_markup(tmp_path: Path) -> None:
    evil = "<script>x</script> & \"quoted\" 'and' <b>bold</b>"
    text = text_of(
        await pdf_export.render(
            a_report(
                rows=rows_of(
                    [{"voucher_date": "2025-05-02", "ledger_name": evil, "amount": Decimal("1")}]
                ),
                total_rows=1,
            )
        ),
        tmp_path,
    )
    assert "<script>" in text  # printed as text, not interpreted


async def test_a_name_with_a_quote_survives_the_page_header(tmp_path: Path) -> None:
    # The company name goes into a CSS `content:` string in @page.
    data = await pdf_export.render(a_report(company_name='Say "hi" \\ Co.'))
    assert 'Say "hi" \\ Co.' in text_of(data, tmp_path)


@pytest.mark.req("D-053")
async def test_past_the_row_cap_the_file_points_at_the_csv_and_keeps_the_full_summary(
    tmp_path: Path,
) -> None:
    pdf_export.PDF_MAX_ROWS, original = 5, pdf_export.PDF_MAX_ROWS
    try:
        report = a_report(
            summary=[SummaryLine("Total Sales Revenue", Decimal("4000"))],
            rows=rows_of(
                [
                    {"voucher_date": "2025-05-02", "ledger_name": f"L{i}", "amount": Decimal("500")}
                    for i in range(8)
                ]
            ),
            total_rows=8,
        )
        text = text_of(await pdf_export.render(report), tmp_path)
    finally:
        pdf_export.PDF_MAX_ROWS = original
    assert "Only the first 5 of 8 rows are printed" in text
    assert "as CSV" in text
    assert "₹4,000.00" in text  # the summary still covers all eight
    assert "L4" in text and "L5" not in text


@pytest.mark.req("D-053")
async def test_no_more_than_the_configured_number_of_pdfs_render_at_once() -> None:
    """D-053 #7a: the cap protects the server, so it is one per-process limit."""
    peak, live = 0, 0
    original = pdf_export.render_html

    def counted(html: str) -> bytes:
        nonlocal peak, live
        live += 1
        peak = max(peak, live)
        try:
            time.sleep(0.05)
            return original(html)
        finally:
            live -= 1

    pdf_export.render_html = counted  # type: ignore[assignment]
    try:
        await asyncio.gather(*(pdf_export.render(a_report()) for _ in range(6)))
    finally:
        pdf_export.render_html = original  # type: ignore[assignment]
    assert peak <= pdf_export.get_settings().pdf_max_concurrent


@pytest.mark.req("D-053")
async def test_a_slow_render_does_not_stop_the_event_loop_answering() -> None:
    """The owner's test: an Agent heartbeat, or any other request, must still be answered while
    a PDF renders. Rendering runs in a worker thread, so the loop keeps turning."""
    original = pdf_export.render_html

    def slow(html: str) -> bytes:
        time.sleep(0.5)  # stands in for a 2,000-row render
        return original(html)

    pdf_export.render_html = slow  # type: ignore[assignment]
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beating = asyncio.create_task(heartbeat())
    try:
        await pdf_export.render(a_report())
    finally:
        pdf_export.render_html = original  # type: ignore[assignment]
        beating.cancel()
    # A blocking render would have let through at most a couple of ticks.
    assert ticks > 20, ticks


@pytest.mark.req("D-053")
async def test_a_two_thousand_row_pdf_renders_whole_in_reasonable_time(tmp_path: Path) -> None:
    """D-053 #7a: the time and memory of a 2,000-row PDF are measured and recorded in
    docs/progress.md. This test holds the shape of that claim - every row printed, more than one
    page, and nothing like a collapse in the time. It deliberately does not run tracemalloc,
    which slows a render about fivefold and would make the figure a lie."""
    rows = [
        {"voucher_date": "2025-05-02", "ledger_name": f"Ledger {i}", "amount": Decimal("100.50")}
        for i in range(pdf_export.PDF_MAX_ROWS)
    ]
    report = a_report(
        summary=[SummaryLine("Total Sales Revenue", Decimal("201000.00"))],
        rows=rows_of(rows),
        total_rows=len(rows),
    )
    started = time.monotonic()
    data = await pdf_export.render(report)
    took = time.monotonic() - started
    text = text_of(data, tmp_path)
    assert "Ledger 1999" in text
    assert "Only the first" not in text  # exactly at the cap, nothing dropped
    pages = int(re.search(r"Page 1 of (\d+)", text).group(1))  # type: ignore[union-attr]
    assert pages > 1
    assert took < 30, took  # measured at ~3 s on the dev Mac; this only catches a collapse


@pytest.mark.req("D-053")
async def test_only_the_bundled_faces_are_ever_embedded(tmp_path: Path) -> None:
    """Nothing may come from the machine's own fonts, or the same report would not look the same
    here, in CI and in Docker - which is the whole reason the fonts are bundled (D-054 #5).

    This caught a real one: the running header and footer are page margin boxes, which inherit
    from the page context rather than from body, so they were being set in whatever serif the
    machine offered.
    """
    data = await pdf_export.render(
        a_report(
            company_name=DEVANAGARI,
            summary=[SummaryLine("Total Sales Revenue", Decimal("1234567.89"))],
            charts=[Chart("By month", [Bar("Apr 2025", Decimal("1"))])],
            rows=rows_of(
                [{"voucher_date": "2025-05-02", "ledger_name": TELUGU, "amount": Decimal("1")}]
            ),
            total_rows=1,
        )
    )
    # NotoSansTelugu-Regular.ttf is embedded as "NotoSansTelugu"; DejaVuSans-Bold keeps its
    # weight. Compare on the file stem with any "-Regular" and the dashes dropped.
    bundled = {
        f.stem.replace("-Regular", "").replace("-", "")
        for f in Path(pdf_export.FONTS).glob("*.ttf")
    }
    used = {
        line.split()[0].split("+")[-1].replace("-", "")
        for line in fonts_of(data, tmp_path).splitlines()[2:]
        if line.strip()
    }
    assert used <= bundled, f"not from fonts/: {used - bundled}"
