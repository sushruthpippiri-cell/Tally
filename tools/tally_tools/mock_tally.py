"""A stand-in for TallyPrime's XML server, for tests (no Tally needed, TEST-1.3).

It answers the same request envelopes the Agent and the capture kit send, in the shape our TDL
is *drafted* to produce. It proves our own tooling (the capture kit on Windows PowerShell, later
the Agent), never Tally's behaviour: only live captures do that (docs/validation-gate.md).

    uv run python -m tally_tools.mock_tally --port 9000 --company "Test Co"
"""

import argparse
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

from tally_contract import tally_constants as tc


@dataclass
class MockConfig:
    companies: list[str] = field(default_factory=lambda: ["Test Co"])
    tdl_loaded: bool = True
    fail_reports: set[str] = field(default_factory=set)  # answered with HTTP 500
    utf16: bool = False  # answer in UTF-16 LE with a BOM (GATE-G35 encodings)


def _guid(name: str) -> str:
    return "guid-" + "".join(ch if ch.isalnum() else "-" for ch in name.lower())


def _report_body(report: str, company: str) -> str:
    """Tiny, fixed responses in our TDL's shape; enough to exercise tools end to end."""
    tag = tc.RECORD_TAGS.get(report)
    root = report.upper()
    if report == tc.INFO_REPORT:
        rows = (
            f"<INFO><TDLVERSION>{tc.TDL_VERSION}</TDLVERSION>"
            f"<COMPANYGUID>{_guid(company)}</COMPANYGUID>"
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


def answer(config: MockConfig, body: bytes) -> tuple[int, bytes]:
    """(HTTP status, response bytes) for one request envelope."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return 200, b"<RESPONSE><LINEERROR>Could not understand the request</LINEERROR></RESPONSE>"
    report = root.findtext("HEADER/ID") or ""
    company = root.findtext(f"BODY/DESC/STATICVARIABLES/{tc.VAR_COMPANY}")
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
    else:
        text = _report_body(report, company or "")
    encoded = b"\xff\xfe" + text.encode("utf-16-le") if config.utf16 else text.encode("utf-8")
    return 200, encoded


def _handler(config: MockConfig) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(200, f"<RESPONSE>{tc.SERVER_RUNNING_TEXT}</RESPONSE>".encode())

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.mock_tally")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--company", action="append", default=[])
    parser.add_argument("--no-tdl", action="store_true")
    parser.add_argument("--fail-report", action="append", default=[])
    parser.add_argument("--utf16", action="store_true")
    args = parser.parse_args(argv)
    config = MockConfig(
        companies=args.company or ["Test Co"],
        tdl_loaded=not args.no_tdl,
        fail_reports=set(args.fail_report),
        utf16=args.utf16,
    )
    server(config, args.port).serve_forever()


if __name__ == "__main__":
    main()
