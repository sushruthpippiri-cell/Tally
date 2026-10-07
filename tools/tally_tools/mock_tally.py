"""A stand-in for TallyPrime's XML server, for tests (no Tally needed, TEST-1.3).

It answers the same request envelopes the Agent and the capture kit send, in the shape our TDL
is *drafted* to produce. It proves our own tooling (the capture kit on Windows PowerShell, later
the Agent), never Tally's behaviour: only live captures do that (docs/validation-gate.md).

    uv run python -m tally_tools.mock_tally --port 9000 --company "Test Co"
"""

import argparse
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from tally_contract import tally_constants as tc


class Reports(dict[str, list["Row"]]):
    """The mock's rows, by report, counting its own mutations.

    `MockConfig.bodies` caches rendered responses, and a stale one is a silently wrong answer -
    which is worse than a slow mock. Relying on callers to invalidate does not work: a test that
    assigns `mock.data["TA_LedgerClosing"] = [...]` directly made reconciliation pass when it
    should have failed. Every mutation in this codebase replaces a report's list rather than
    editing it in place (Row is frozen), so counting assignments catches all of them, in O(1).
    """

    version: int = 0

    def __setitem__(self, key: str, value: list["Row"]) -> None:
        self.version += 1
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self.version += 1
        super().__delitem__(key)


@dataclass(frozen=True)
class Row:
    """One record the mock serves: its GUID and ALTERID (for windows and key lists), its XML
    as our TDL is drafted to emit it, and, for vouchers, its date (for date windows)."""

    guid: str
    alter_id: int
    xml: str
    day: date | None = None


@dataclass
class MockConfig:
    companies: list[str] = field(default_factory=lambda: ["Test Co"])
    tdl_loaded: bool = True
    fail_reports: set[str] = field(default_factory=set)  # answered with HTTP 500
    utf16: bool = False  # answer in UTF-16 LE with a BOM (GATE-G35 encodings)
    delay_seconds: float = 0  # answer this late (the Agent's timeout, AGT-4.3)
    guids: dict[str, str] = field(default_factory=dict)  # company -> GUID, e.g. a different one
    tdl_version: str = tc.TDL_VERSION
    requests: list[tuple[str, str | None]] = field(default_factory=list)  # (report, company)
    calls: list[dict[str, str]] = field(default_factory=list)  # report + static variables
    # Either form: __post_init__ wraps a plain dict in the counting subclass.
    data: Reports | dict[str, list[Row]] = field(default_factory=Reports)
    slow: dict[str, list[float]] = field(default_factory=dict)  # report -> delays, one per call
    # The period selected in Tally: what a request that names no dates gets (GATE-G37, as
    # drafted). None: no limit.
    selected_period: tuple[date, date] | None = None
    # Rendered bodies, keyed by (report, window). At the SRS 17.2 size a full sync asks for the
    # same 100,000-voucher report once per batch, and rebuilding it each time - plus the
    # reconciliation scan, which reads every voucher with a regex - is most of the mock's cost.
    # `invalidate()` clears both; every mutation helper calls it, so a cached body can never
    # outlive the data it was built from (P16.5).
    bodies: dict[tuple[str, tuple[Any, ...]], str] = field(default_factory=dict, repr=False)
    recon: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    cached_version: int = field(default=-1, repr=False)

    def reports(self) -> Reports:
        """`data` as the counting subclass, wrapping it if a caller replaced the whole
        attribute (`mock.data = sample_company(...)`, which __post_init__ never sees). Any
        rendered body from before the swap is dropped."""
        if not isinstance(self.data, Reports):
            self.data = Reports(self.data)
            self.cached_version = -1  # whatever was cached belongs to the old rows
        return self.data

    def __post_init__(self) -> None:
        # Callers pass a plain dict (sample_company's return, a literal in a test); the counting
        # subclass is what makes the response cache safe, so wrap it here rather than asking
        # every caller to remember.
        if not isinstance(self.data, Reports):
            self.data = Reports(self.data)

    def invalidate(self) -> None:
        self.bodies.clear()
        self.recon.clear()

    def fresh(self) -> None:
        """Drop the caches if the rows have changed since they were filled.

        `reports()` is called first, on its own line: it may reset `cached_version` when it wraps
        a swapped-in dict, and Python evaluates the left side of a comparison first - so reading
        `self.cached_version` inside the condition saw the value from before the wrap and the
        cache survived a swap it should not have.
        """
        reports = self.reports()
        if self.cached_version != reports.version:
            self.invalidate()
            self.cached_version = reports.version


def company_guid(name: str) -> str:
    """The GUID the mock reports for a company (unless `guids` overrides it)."""
    return "guid-" + "".join(ch if ch.isalnum() else "-" for ch in name.lower())


def _report_body(config: "MockConfig", report: str, company: str) -> str:
    """Tiny, fixed responses in our TDL's shape; enough to exercise tools end to end."""
    tag = tc.RECORD_TAGS.get(report)
    root = report.upper()
    if report == tc.INFO_REPORT:
        rows = (
            f"<INFO><TDLVERSION>{escape(config.tdl_version)}</TDLVERSION>"
            f"<COMPANYGUID>{config.guids.get(company, company_guid(company))}</COMPANYGUID>"
            f"<COMPANYNAME>{escape(company)}</COMPANYNAME></INFO>"
        )
    elif tag == "KEY":
        rows = "<KEY><GUID>k-1</GUID><ALTERID>1</ALTERID></KEY>"
    elif tag == "VOUCHER":
        rows = (
            "<VOUCHER><GUID>voucher-1</GUID><ALTERID>1</ALTERID>"
            "<VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><DATE>20240401</DATE>"
            "<LEDGERENTRY><LEDGERNAME>Cash</LEDGERNAME><AMOUNT>-100.00</AMOUNT>"
            "<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE></LEDGERENTRY>"
            "<LEDGERENTRY><LEDGERNAME>Sales</LEDGERNAME><AMOUNT>100.00</AMOUNT>"
            "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></LEDGERENTRY></VOUCHER>"
        )
    elif tag is not None:
        rows = f"<{tag}><GUID>{tag.lower()}-1</GUID><ALTERID>1</ALTERID><NAME>Sample</NAME></{tag}>"
    else:  # a built-in report (capture kit reference step)
        root, rows = "BUILTIN", f"<REPORT>{escape(report)}</REPORT>"
    return f"<ENVELOPE><{root}>{rows}</{root}></ENVELOPE>"


def _served(config: MockConfig, report: str) -> bool:
    return report in config.data or report.removesuffix("Keys") in config.data


def _day(value: str | None) -> date | None:
    return datetime.strptime(value, tc.REQUEST_DATE_FORMAT).date() if value else None


_ENTRY = re.compile(
    r"<LEDGERENTRY><LEDGERNAME>(?P<name>[^<]*)</LEDGERNAME><LEDGERGUID>(?P<guid>[^<]*)"
    r"</LEDGERGUID><AMOUNT>(?P<amount>[^<]*)</AMOUNT>"
)


def _recon_totals(config: MockConfig, variables: dict[str, str]) -> str:
    """What our TA_ReconTotals is drafted to return (GATE-G36): per (ledger, voucher type),
    the debit and credit sums of the non-cancelled vouchers dated in the period. Computed from
    the mock's own vouchers, as Tally computes it from its own."""
    period = (variables.get(tc.VAR_FROM_DATE, ""), variables.get(tc.VAR_TO_DATE, ""))
    config.fresh()
    cached = config.recon.get(period)
    if cached is not None:
        return cached
    start = _day(variables.get(tc.VAR_FROM_DATE)) or date.min  # always sent (D-048 #2)
    end = _day(variables.get(tc.VAR_TO_DATE)) or date.max
    sums: dict[tuple[str, str, str], list[Decimal]] = {}
    for row in config.data.get("TA_Vouchers", []):
        if "<ISCANCELLED>Yes" in row.xml or row.day is None or not (start <= row.day <= end):
            continue
        vtype = re.search(r"<VOUCHERTYPEGUID>([^<]*)<", row.xml)
        for m in _ENTRY.finditer(row.xml):
            amount = Decimal(m["amount"])  # negative = debit (GATE-G23)
            key = (m["guid"], m["name"], vtype[1] if vtype else "")
            debit, credit = sums.setdefault(key, [Decimal(0), Decimal(0)])
            if amount < 0:
                debit -= amount
            else:
                credit += amount
            sums[key] = [debit, credit]
    body = "".join(
        f"<RECON_TOTAL><LEDGERGUID>{guid}</LEDGERGUID><LEDGERNAME>{escape(name)}</LEDGERNAME>"
        f"<VOUCHERTYPEGUID>{vtype}</VOUCHERTYPEGUID>"
        f"<FROMDATE>{variables[tc.VAR_FROM_DATE]}</FROMDATE>"
        f"<ASOFDATE>{variables[tc.VAR_TO_DATE]}</ASOFDATE>"
        f"<DEBIT>{debit}</DEBIT><CREDIT>{credit}</CREDIT></RECON_TOTAL>"
        for (guid, name, vtype), (debit, credit) in sorted(sums.items())
    )
    rendered = f"<ENVELOPE><TA_RECONTOTALS>{body}</TA_RECONTOTALS></ENVELOPE>"
    config.recon[period] = rendered
    return rendered


def _data_body(config: MockConfig, report: str, variables: dict[str, str]) -> str:
    """Rows filtered as our TDL is drafted to filter them: the ALTERID window (from, to], 0/0
    meaning everything (D-013), and the date window for rows that carry a date.

    Cached per (report, window): the filtering and the join are pure functions of those, and at
    benchmark size this is called once per upload batch over the same 100,000 rows.
    """
    key = (
        report,
        (
            variables.get(tc.VAR_FROM_ALTER_ID, ""),
            variables.get(tc.VAR_TO_ALTER_ID, ""),
            variables.get(tc.VAR_FROM_DATE, ""),
            variables.get(tc.VAR_TO_DATE, ""),
        ),
    )
    config.fresh()
    cached = config.bodies.get(key)
    if cached is not None:
        return cached
    source = report if report in config.data else report.removesuffix("Keys")
    low = int(variables.get(tc.VAR_FROM_ALTER_ID) or 0)
    high = int(variables.get(tc.VAR_TO_ALTER_ID) or 0)
    start, end = _day(variables.get(tc.VAR_FROM_DATE)), _day(variables.get(tc.VAR_TO_DATE))
    if config.selected_period is not None:
        start = start or config.selected_period[0]
        end = end or config.selected_period[1]
    rows = [
        r
        for r in config.data[source]
        if ((low, high) == (0, 0) or low < r.alter_id <= high)
        and (r.day is None or ((start is None or r.day >= start) and (end is None or r.day <= end)))
    ]
    if report in (tc.STOCK_CLOSING_REPORT, tc.LEDGER_CLOSING_REPORT, tc.RECONCILIATION_REPORT):
        # "as of" is the requested SVTODATE (G18, G19); totals also echo SVFROMDATE (G36)
        as_of, since = variables.get(tc.VAR_TO_DATE, ""), variables.get(tc.VAR_FROM_DATE, "")
        body = "".join(r.xml.replace("{as_of}", as_of).replace("{from}", since) for r in rows)
    elif report == source:
        body = "".join(r.xml for r in rows)
    else:
        body = "".join(
            f"<KEY><GUID>{r.guid}</GUID><ALTERID>{r.alter_id}</ALTERID></KEY>" for r in rows
        )
    rendered = f"<ENVELOPE><{report.upper()}>{body}</{report.upper()}></ENVELOPE>"
    config.bodies[key] = rendered
    return rendered


def answer(config: MockConfig, body: bytes) -> tuple[int, bytes]:
    """(HTTP status, response bytes) for one request envelope."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return 200, b"<RESPONSE><LINEERROR>Could not understand the request</LINEERROR></RESPONSE>"
    report = root.findtext("HEADER/ID") or ""
    company = root.findtext(f"BODY/DESC/STATICVARIABLES/{tc.VAR_COMPANY}")
    variables = {v.tag: v.text or "" for v in root.iterfind("BODY/DESC/STATICVARIABLES/*")}
    config.requests.append((report, company))
    config.calls.append({"report": report, **variables})
    delays = config.slow.get(report)
    if delays:
        time.sleep(delays.pop(0))
    if report in config.fail_reports:
        return 500, b"<RESPONSE>Internal error</RESPONSE>"
    if report == tc.BUILTIN_COMPANY_LIST:
        names = "".join(f"<COMPANY><NAME>{escape(c)}</NAME></COMPANY>" for c in config.companies)
        text = f"<ENVELOPE><COLLECTION>{names}</COLLECTION></ENVELOPE>"
    elif company is not None and company not in config.companies:
        text = (
            f"<RESPONSE><LINEERROR>{tc.COMPANY_NOT_LOADED_MARKERS[0]} "
            f"to '{escape(company)}'</LINEERROR></RESPONSE>"
        )
    elif report.startswith("TA_") and (not config.tdl_loaded or report not in tc.RECORD_TAGS):
        text = (
            f"<RESPONSE><LINEERROR>{tc.REPORT_NOT_FOUND_MARKERS[0]} "
            f"'{escape(report)}'!</LINEERROR></RESPONSE>"
        )
    elif report == tc.RECONCILIATION_REPORT and report not in config.data:
        text = _recon_totals(config, variables)
    elif _served(config, report):
        text = _data_body(config, report, variables)
    else:
        text = _report_body(config, report, company or "")
    encoded = b"\xff\xfe" + text.encode("utf-16-le") if config.utf16 else text.encode("utf-8")
    return 200, encoded


def _handler(config: MockConfig) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(200, f"<RESPONSE>{tc.SERVER_RUNNING_TEXT}</RESPONSE>".encode())

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if config.delay_seconds:
                time.sleep(config.delay_seconds)
            self._send(*answer(config, self.rfile.read(length)))

        def _send(self, status: int, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # quiet
            pass

    return Handler


def server(config: MockConfig, port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _handler(config))


@contextmanager
def running(config: MockConfig) -> Iterator[str]:
    """Serve on a free port in a thread; yields the base URL."""
    httpd = server(config)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


_RECORD = re.compile(r"<(?P<tag>[A-Z_]+)><GUID>(?P<guid>[^<]*)</GUID>")
_ALTER = re.compile(r"<ALTERID>(\d+)</ALTERID>")
_DATE = re.compile(r"<DATE>(\d{8})</DATE>")


def load_dataset(directory: Path) -> MockConfig:
    """Serve the generated benchmark dataset (`make dataset`) instead of the 12-voucher sample.

    The files are split back into `Row`s because the mock filters by ALTERID and date, which it
    cannot do over one opaque blob. The split is a one-off cost at startup; `MockConfig.bodies`
    then keeps each rendered window, so a full sync pays for the join once rather than once per
    batch (P16.5).
    """
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    company = manifest["company"]
    data: dict[str, list[Row]] = {}
    for path in sorted(directory.glob("TA_*.xml")):
        report = path.stem
        text = path.read_text(encoding="utf-8")
        tag = tc.RECORD_TAGS.get(report)
        if tag is None:
            continue
        rows: list[Row] = []
        for chunk in text.split(f"<{tag}>")[1:]:
            record = f"<{tag}>" + chunk.split(f"</{tag}>")[0] + f"</{tag}>"
            guid = _RECORD.match(record)
            alter = _ALTER.search(record)
            day = _DATE.search(record)
            rows.append(
                Row(
                    guid["guid"] if guid else "",
                    int(alter[1]) if alter else 0,
                    record,
                    datetime.strptime(day[1], tc.RESPONSE_DATE_FORMAT).date() if day else None,
                )
            )
        data[report] = rows
    # TA_Info reports the mock's own state, not the dataset's, so the company GUID comes from
    # the manifest rather than a file (see dataset_gen).
    return MockConfig(
        companies=[company["name"]], guids={company["name"]: company["guid"]}, data=Reports(data)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.mock_tally")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--company", action="append", default=[])
    parser.add_argument("--no-tdl", action="store_true")
    parser.add_argument("--fail-report", action="append", default=[])
    parser.add_argument("--utf16", action="store_true")
    parser.add_argument("--sample", action="store_true", help="serve sample_company() data")
    parser.add_argument(
        "--dataset", type=Path, help="serve a generated dataset directory (`make dataset`)"
    )
    args = parser.parse_args(argv)
    if args.dataset:
        config = load_dataset(args.dataset)
        config.tdl_loaded = not args.no_tdl
        config.fail_reports = set(args.fail_report)
        config.utf16 = args.utf16
        server(config, args.port).serve_forever()
        return
    companies = args.company or ["Test Co"]
    config = MockConfig(
        companies=companies,
        tdl_loaded=not args.no_tdl,
        fail_reports=set(args.fail_report),
        utf16=args.utf16,
        data=sample_company(companies[0]) if args.sample else {},
    )
    server(config, args.port).serve_forever()


# --- a small, consistent company (P7): masters, vouchers across months, stock ---------------


def _fmt(day: date) -> str:
    return day.strftime(tc.RESPONSE_DATE_FORMAT)


def sample_company(
    company: str = "Sharma Traders", *, vouchers: int = 12, first_day: date = date(2024, 4, 1)
) -> dict[str, list[Row]]:
    """Masters share one ALTERID sequence and vouchers another, as Tally keeps them (G33)."""
    guid = company_guid(company)
    groups = [
        ("g-sales", "Sales Accounts", "No", "No", "Yes"),
        ("g-sd", "Sundry Debtors", "No", "Yes", "No"),
        ("g-tax", "Duties & Taxes", "No", "No", "No"),
    ]
    master: dict[str, list[Row]] = {"TA_Groups": [], "TA_Ledgers": [], "TA_VoucherTypes": []}
    alter = 1
    for g, name, revenue, deemed, _gp in groups:
        alter += 1
        master["TA_Groups"].append(
            Row(
                g,
                alter,
                f"<GROUP><GUID>{g}</GUID><ALTERID>{alter}</ALTERID><NAME>{escape(name)}</NAME>"
                f"<PARENT>Primary</PARENT><ISREVENUE>{revenue}</ISREVENUE>"
                f"<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE></GROUP>",
            )
        )
    for led, name, parent in (
        ("l-cust", "Customer A", "g-sd"),
        ("l-sales", "Sales - Retail", "g-sales"),
        ("l-gst", "Output GST", "g-tax"),
    ):
        alter += 1
        parent_name = next(n for g, n, *_ in groups if g == parent)
        master["TA_Ledgers"].append(
            Row(
                led,
                alter,
                f"<LEDGER><GUID>{led}</GUID><ALTERID>{alter}</ALTERID><NAME>{escape(name)}</NAME>"
                f"<PARENT>{escape(parent_name)}</PARENT><PARENTGUID>{parent}</PARENTGUID>"
                "<OPENINGBALANCE></OPENINGBALANCE></LEDGER>",
            )
        )
    alter += 1
    master["TA_VoucherTypes"].append(
        Row(
            "vt-sales",
            alter,
            f"<VOUCHER_TYPE><GUID>vt-sales</GUID><ALTERID>{alter}</ALTERID><NAME>Sales</NAME>"
            "<PARENT>Sales</PARENT></VOUCHER_TYPE>",
        )
    )
    alter += 1
    stock = Row(
        "s-soap",
        alter,
        f"<STOCK_ITEM><GUID>s-soap</GUID><ALTERID>{alter}</ALTERID><NAME>Soap</NAME>"
        "<BASEUNIT>Nos</BASEUNIT></STOCK_ITEM>",
    )
    alter += 1
    centre = Row(
        "cc-1",
        alter,
        f"<COST_CENTRE><GUID>cc-1</GUID><ALTERID>{alter}</ALTERID><NAME>Retail</NAME>"
        "<PARENT>Primary</PARENT></COST_CENTRE>",
    )
    rows = [
        voucher_row(i, i, first_day + timedelta(days=30 * (i - 1))) for i in range(1, vouchers + 1)
    ]
    company_row = Row(
        guid,
        1,
        f"<COMPANY><GUID>{guid}</GUID><ALTERID>1</ALTERID><NAME>{escape(company)}</NAME>"
        f"<BOOKSFROM>{_fmt(first_day)}</BOOKSFROM><FYSTART>{_fmt(first_day)}</FYSTART>"
        f"<LASTMASTERALTERID>{alter}</LASTMASTERALTERID>"
        f"<LASTVOUCHERALTERID>{vouchers}</LASTVOUCHERALTERID></COMPANY>",
    )
    return {
        "TA_Company": [company_row],
        **master,
        "TA_StockItems": [stock],
        "TA_CostCentres": [centre],
        "TA_Vouchers": rows,
        tc.STOCK_CLOSING_REPORT: [
            Row(
                "s-soap",
                0,
                "<STOCK_CLOSING><GUID>s-soap</GUID><ASOFDATE>{as_of}</ASOFDATE>"
                "<CLOSINGQTY>40 Nos</CLOSINGQTY></STOCK_CLOSING>",
            )
        ],
        # Tally's closing balances on any date in FY2025-26 or later (the sample's vouchers
        # are all in FY2024-25, so income has reset to zero, ACC-9.2). Tally shows a debit
        # negative (GATE-G23). Totals are computed from the vouchers (`_recon_totals`).
        tc.LEDGER_CLOSING_REPORT: [
            Row(
                led,
                0,
                f"<LEDGER_CLOSING><GUID>{led}</GUID><NAME>{escape(name)}</NAME>"
                f"<ASOFDATE>{{as_of}}</ASOFDATE><CLOSINGBALANCE>{balance}</CLOSINGBALANCE>"
                "</LEDGER_CLOSING>",
            )
            for led, name, balance in (
                ("l-cust", "Customer A", f"-{1180 * vouchers:.2f}"),
                ("l-sales", "Sales - Retail", "0.00"),
                ("l-gst", "Output GST", f"{180 * vouchers:.2f}"),
            )
        ],
    }


def voucher_row(i: int, alter: int, day: date, amount: str = "1180.00") -> Row:
    """A balanced sale with GUID `v-{i}`: customer debit = sales + 18% GST credit."""
    total = float(amount)
    sales, tax = f"{total / 1.18:.2f}", f"{total - round(total / 1.18, 2):.2f}"
    return Row(
        f"v-{i}",
        alter,
        f"<VOUCHER><GUID>v-{i}</GUID><ALTERID>{alter}</ALTERID><VOUCHERNUMBER>S-{i}</VOUCHERNUMBER>"
        f"<VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><VOUCHERTYPEGUID>vt-sales</VOUCHERTYPEGUID>"
        f"<DATE>{_fmt(day)}</DATE>"
        f"<LEDGERENTRY><LEDGERNAME>Customer A</LEDGERNAME><LEDGERGUID>l-cust</LEDGERGUID>"
        f"<AMOUNT>-{amount}</AMOUNT><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE></LEDGERENTRY>"
        f"<LEDGERENTRY><LEDGERNAME>Sales - Retail</LEDGERNAME><LEDGERGUID>l-sales</LEDGERGUID>"
        f"<AMOUNT>{sales}</AMOUNT><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></LEDGERENTRY>"
        f"<LEDGERENTRY><LEDGERNAME>Output GST</LEDGERNAME><LEDGERGUID>l-gst</LEDGERGUID>"
        f"<AMOUNT>{tax}</AMOUNT><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></LEDGERENTRY></VOUCHER>",
        day,
    )


# --- edits between runs (P7.8): Tally raises the ALTERID of what it changes -------------------
#
# These take the MockConfig rather than its `data` dict so that each one invalidates the rendered
# bodies (P16.5). Passing the dict alone would let a caller mutate the data and be served a body
# built before the change - which is exactly the bug a cache invites.


def _last_voucher_alter_id(data: dict[str, list[Row]]) -> int:
    return max((r.alter_id for r in data["TA_Vouchers"]), default=0)


def _replace(config: MockConfig, report: str, row: Row) -> None:
    data = config.data
    config.invalidate()
    data[report] = [row if r.guid == row.guid else r for r in data[report]]
    company = data["TA_Company"][0]
    xml = re.sub(
        r"<LASTVOUCHERALTERID>\d+</LASTVOUCHERALTERID>",
        f"<LASTVOUCHERALTERID>{_last_voucher_alter_id(data)}</LASTVOUCHERALTERID>",
        company.xml,
    )
    data["TA_Company"] = [Row(company.guid, company.alter_id, xml, company.day)]


def _voucher(data: dict[str, list[Row]], guid: str) -> Row:
    return next(r for r in data["TA_Vouchers"] if r.guid == guid)


def edit_voucher(config: MockConfig, guid: str, amount: str) -> Row:
    """The voucher's amount changes and it gets the next ALTERID, as a Tally edit does."""
    data = config.data
    old = _voucher(data, guid)
    assert old.day is not None
    row = voucher_row(
        int(guid.removeprefix("v-")), _last_voucher_alter_id(data) + 1, old.day, amount
    )
    _replace(config, "TA_Vouchers", row)
    return row


def add_voucher(config: MockConfig, day: date, amount: str = "1180.00") -> Row:
    """A new voucher entered in Tally, dated `day` (a post-dated one if after today), with the
    next ALTERID."""
    data = config.data
    alter = _last_voucher_alter_id(data) + 1
    row = voucher_row(len(data["TA_Vouchers"]) + 1, alter, day, amount)
    data["TA_Vouchers"] = [*data["TA_Vouchers"], row]
    _replace(config, "TA_Vouchers", row)
    return row


def cancel_voucher(config: MockConfig, guid: str) -> Row:
    """Cancelled in Tally: kept, flagged, with a new ALTERID (GATE-G9)."""
    data = config.data
    old = _voucher(data, guid)
    alter = _last_voucher_alter_id(data) + 1
    xml = re.sub(r"<ALTERID>\d+</ALTERID>", f"<ALTERID>{alter}</ALTERID>", old.xml, count=1)
    row = Row(
        guid, alter, xml.replace("</VOUCHER>", "<ISCANCELLED>Yes</ISCANCELLED></VOUCHER>"), old.day
    )
    _replace(config, "TA_Vouchers", row)
    return row


def delete(config: MockConfig, report: str, guid: str) -> None:
    """Deleted in Tally: gone from every pull and key list, with no ALTERID signal (G11)."""
    config.invalidate()
    config.data[report] = [r for r in config.data[report] if r.guid != guid]


if __name__ == "__main__":
    main()
