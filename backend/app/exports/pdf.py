"""PDF export (EXP-1.1, EXP-1.2; D-053 #7).

WeasyPrint over hand-written HTML, with the fonts bundled in `fonts/` so this machine, CI and
the Docker image embed the same faces (see `fonts/README.md`). Charts are small hand-written
SVG from the same series the screen draws - no plotting library, and no value axis: the labels
carry the figures, exactly as `components/Chart.tsx` does (D-053 #5).

Rendering is synchronous and CPU-heavy, so it runs in a worker thread, at most
`PDF_MAX_CONCURRENT` at a time across the whole process (D-053 #7a as amended by the owner).
"""

import asyncio
import weakref
from decimal import Decimal
from html import escape
from pathlib import Path

from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

from app.core.config import get_settings
from app.exports.money import format_money, format_quantity
from app.exports.report import Chart, Column, Report

FONTS = Path(__file__).parent / "fonts"
PDF_MAX_ROWS = 2000  # past this, the file points at the CSV; the summary still covers every row
CAPPED = (
    "Only the first {shown:,} of {total:,} rows are printed. Export the same view as CSV for "
    "every row; the summary figures above cover all of them."
)

# One family per face, so the stack falls back per character and `pdffonts` names the face that
# was actually embedded (fonts/README.md).
_FACES = [
    ("DejaVu Sans", "DejaVuSans.ttf", "normal"),
    ("DejaVu Sans", "DejaVuSans-Bold.ttf", "bold"),
    *[
        (f"Noto Sans {script}", f"NotoSans{script}-Regular.ttf", "normal")
        for script in (
            "Devanagari",
            "Bengali",
            "Gurmukhi",
            "Gujarati",
            "Oriya",
            "Tamil",
            "Telugu",
            "Kannada",
            "Malayalam",
        )
    ],
]
FONT_STACK = ", ".join(f'"{name}"' for name in dict.fromkeys(f for f, _, _ in _FACES))
_FONT_FACES = "\n".join(
    f'@font-face {{ font-family: "{family}"; src: url("{file}"); font-weight: {weight}; }}'
    for family, file, weight in _FACES
)


def _style(report: Report) -> str:
    return f"""
{_FONT_FACES}
@page {{
  size: A4 landscape;
  margin: 14mm 12mm 16mm 12mm;
  @top-left {{ content: "{_css(report.company_name)}"; font-size: 8pt; color: #475569; }}
  @top-right {{ content: "{_css(report.title)}"; font-size: 8pt; color: #475569; }}
  @bottom-left {{ content: "{_css(_range(report))}"; font-size: 8pt; color: #475569; }}
  @bottom-right {{
    content: "Page " counter(page) " of " counter(pages);
    font-size: 8pt; color: #475569;
  }}
}}
body {{ font-family: {FONT_STACK}; font-size: 8.5pt; color: #0f172a; }}
h1 {{ font-size: 15pt; margin: 0 0 1mm; }}
h2 {{ font-size: 10pt; margin: 5mm 0 1.5mm; }}
.company {{ font-size: 10pt; margin: 0 0 3mm; color: #334155; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 0.3pt solid #cbd5e1; padding: 1.2mm 2mm; text-align: left; }}
thead th {{ background: #f1f5f9; font-weight: bold; }}
thead {{ display: table-header-group; }}
tr {{ page-break-inside: avoid; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.meta td:first-child, .summary td:first-child {{ color: #475569; width: 45mm; }}
.meta {{ width: auto; }}
.meta td {{ border: none; padding: 0.6mm 4mm 0.6mm 0; }}
.summary td {{ border-bottom: none; padding: 0.8mm 2mm; }}
.summary .figure {{ font-weight: bold; }}
.note {{ color: #334155; margin: 1mm 0 0; }}
.chart {{ margin: 3mm 0; }}
.capped {{ margin-top: 3mm; font-weight: bold; }}
"""


def _css(text: str) -> str:
    """A string inside a CSS `content:` declaration."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _range(report: Report) -> str:
    for label, value in report.meta:
        if label in ("Date range", "As of"):
            return f"{label}: {value}"
    return ""


def _figure(amount: Decimal | None, direction: str | None, kind: str) -> str:
    if amount is None:
        return "unavailable"  # ACC-9.6: never "₹0.00"
    if kind == "integer":
        return f"{amount.to_integral_value():,}" if amount == amount.to_integral() else str(amount)
    shown = format_money(amount)
    return f"{shown} {direction}" if direction else shown


def _cell(value: object, column: Column) -> str:
    if column.kind in ("amount", "signed_amount"):
        return "" if value is None else format_money(value)  # type: ignore[arg-type]
    if column.kind == "quantity":
        return format_quantity(value)  # type: ignore[arg-type]
    if column.kind == "integer":
        return "" if value is None else str(value)
    return "" if value is None else str(value)


# --- the SVG charts (EXP-1.2) ------------------------------------------------------------

_W, _ROW, _LABEL, _VALUE = 720, 14, 150, 110


def _svg(chart: Chart) -> str:
    """Horizontal bars, longest = the largest figure. No value axis; each bar carries its own
    amount as text, so the figure the owner reads is the backend's own (D-053 #5)."""
    bars = [b for b in chart.bars if b.amount is not None]
    if not bars:
        return ""
    widest = max((abs(b.amount or Decimal(0)) for b in bars), default=Decimal(0))
    span = _W - _LABEL - _VALUE - 10
    height = _ROW * len(bars) + 8
    parts = [
        f'<svg class="chart" xmlns="http://www.w3.org/2000/svg" width="{_W}" '
        f'height="{height}" viewBox="0 0 {_W} {height}" role="img" '
        f'aria-label="{escape(chart.title)}">'
    ]
    for index, bar in enumerate(bars):
        amount = bar.amount or Decimal(0)
        length = 0 if not widest else int(span * abs(amount) / widest)
        y = index * _ROW + 4
        negative = amount < 0
        parts.append(
            f'<text x="0" y="{y + 9}" font-size="8">{escape(bar.label)}</text>'
            f'<rect x="{_LABEL}" y="{y + 2}" width="{max(length, 1)}" height="{_ROW - 6}" '
            f'fill="{"#fecaca" if negative else "#bfdbfe"}" '
            f'stroke="{"#b91c1c" if negative else "#1d4ed8"}" stroke-width="0.7"'
            # Not colour alone (NFR-UI-2): an outgoing bar is hatched as well as pale red.
            f"{" stroke-dasharray='2 1'" if negative else ''} />"
            f'<text x="{_LABEL + max(length, 1) + 4}" y="{y + 9}" font-size="8">'
            f"{escape(format_money(amount))}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


# --- the document ------------------------------------------------------------------------


def document(report: Report, rows: list[dict[str, object]]) -> str:
    """The whole report as one HTML document. Every value is escaped: ledger, item and company
    names come from the customer's Tally."""
    meta = "".join(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>" for label, value in report.meta
    )
    summary = "".join(
        f"<tr><td>{escape(line.label)}</td>"
        f'<td class="num figure">{escape(_figure(line.amount, line.direction, line.kind))}</td>'
        f"<td>{escape(line.note or '')}</td></tr>"
        for line in report.summary
    )
    notes = "".join(f'<p class="note">{escape(note)}</p>' for note in report.notes)
    # A chart with nothing to draw gets no heading either: an empty box reads as a bug.
    drawn = [(chart, _svg(chart)) for chart in report.charts]
    charts = "".join(f"<h2>{escape(chart.title)}</h2>{svg}" for chart, svg in drawn if svg)
    numeric = {"amount", "signed_amount", "quantity", "integer"}
    head = "".join(
        f'<th class="{"num" if c.kind in numeric else ""}">{escape(c.heading)}</th>'
        for c in report.columns
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"num" if c.kind in numeric else ""}">'
            f"{escape(_cell(row.get(c.key), c))}</td>"
            for c in report.columns
        )
        + "</tr>"
        for row in rows
    )
    total = report.total_rows if report.total_rows is not None else len(rows)
    capped = (
        f'<p class="capped">{escape(CAPPED.format(shown=len(rows), total=total))}</p>'
        if total > len(rows)
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(report.title)}</title>
<style>{_style(report)}</style></head><body>
<h1>{escape(report.title)}</h1>
<p class="company">{escape(report.company_name)}</p>
<table class="meta">{meta}</table>
<h2>Summary</h2>
<table class="summary">{summary}</table>
{notes}
{charts}
<h2>Detail{f" ({total:,} rows)" if total else ""}</h2>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
{capped}
</body></html>
"""


# --- the worker (D-053 #7a) --------------------------------------------------------------

# One cap per process. Keyed by the running loop because an asyncio primitive binds to the loop
# that first awaits it, and the test suite runs a loop per test; production has exactly one.
_limits: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _limit() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    limit = _limits.get(loop)
    if limit is None:
        limit = asyncio.Semaphore(get_settings().pdf_max_concurrent)
        _limits[loop] = limit
    return limit


def render_html(html: str) -> bytes:
    """Blocking. A `FontConfiguration` per render: it holds fontconfig state, and a render runs
    on a worker thread."""
    config = FontConfiguration()
    style = CSS(string=_FONT_FACES, base_url=f"{FONTS}/", font_config=config)
    return HTML(string=html, base_url=f"{FONTS}/").write_pdf(  # type: ignore[no-any-return]
        stylesheets=[style], font_config=config
    )


async def render(report: Report) -> bytes:
    """The report as PDF bytes, rendered off the event loop under the process-wide cap, with at
    most `PDF_MAX_ROWS` detail rows (the summary always covers every row)."""
    rows: list[dict[str, object]] = []
    async for row in report.rows:
        rows.append(row)
        if len(rows) >= PDF_MAX_ROWS:
            break
    html = document(report, rows)
    # ponytail: a thread, not a process. WeasyPrint releases the GIL inside Pango/cairo but not
    # in its own Python, so a render adds latency to other requests rather than blocking them.
    # Upgrade path if that is not enough: a ProcessPoolExecutor of the same size.
    async with _limit():
        return await asyncio.to_thread(render_html, html)
