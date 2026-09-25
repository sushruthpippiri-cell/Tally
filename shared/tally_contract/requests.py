"""XML export requests the Agent (and the capture kit) sends to TallyPrime (P4.3, SRS 19.1).

Pure functions returning UTF-8 bytes. Values may be real (dates, ints) or template
placeholders like "{{COMPANY}}" (strings pass through unchanged, XML-escaped), which is how the
capture kit's request templates are generated from this same code.
"""

import xml.etree.ElementTree as ET
from datetime import date

from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType

Value = str | int | date


def _text(value: Value) -> str:
    if isinstance(value, date):
        return value.strftime(tc.REQUEST_DATE_FORMAT)
    return str(value)


def envelope(
    report_id: str,
    static_variables: dict[str, Value],
    *,
    request_type: str = tc.REQUEST_TYPE_DATA,
    date_variables: tuple[str, ...] = (),
) -> bytes:
    """One export ENVELOPE. `date_variables` are sent with TYPE="Date"."""
    root = ET.Element("ENVELOPE")
    header = ET.SubElement(root, "HEADER")
    for tag, text in (
        ("VERSION", tc.ENVELOPE_VERSION),
        ("TALLYREQUEST", tc.REQUEST_EXPORT),
        ("TYPE", request_type),
        ("ID", report_id),
    ):
        ET.SubElement(header, tag).text = text
    desc = ET.SubElement(ET.SubElement(root, "BODY"), "DESC")
    variables = ET.SubElement(desc, "STATICVARIABLES")
    ET.SubElement(variables, tc.VAR_EXPORT_FORMAT).text = tc.EXPORT_FORMAT_XML
    for name, value in static_variables.items():
        element = ET.SubElement(variables, name)
        if name in date_variables:
            element.set("TYPE", "Date")
        element.text = _text(value)
    ET.indent(root)
    xml: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return xml + b"\n"


def _dates(date_from: Value | None, date_to: Value | None) -> dict[str, Value]:
    dates: dict[str, Value] = {}
    if date_from is not None:
        dates[tc.VAR_FROM_DATE] = date_from
    if date_to is not None:
        dates[tc.VAR_TO_DATE] = date_to
    return dates


DATE_VARS = (tc.VAR_FROM_DATE, tc.VAR_TO_DATE)


def info(company: Value) -> bytes:
    """TDL version and the named company's GUID (VER-1.1, AGT-3.2, FR-1.4)."""
    return envelope(tc.INFO_REPORT, {tc.VAR_COMPANY: company})


def collection(
    collection_type: CollectionType,
    company: Value,
    *,
    from_alter_id: Value = 0,
    to_alter_id: Value = 0,
    date_from: Value | None = None,
    date_to: Value | None = None,
    keys_only: bool = False,
) -> bytes:
    """One page of a collection: ALTERID window (from, to], 0/0 = everything (D-013), an
    optional date window, and the key-only variant (FR-1.2)."""
    reports = tc.KEY_REPORTS if keys_only else tc.REPORTS
    return envelope(
        reports[collection_type],
        {
            tc.VAR_COMPANY: company,
            **_dates(date_from, date_to),
            tc.VAR_FROM_ALTER_ID: from_alter_id,
            tc.VAR_TO_ALTER_ID: to_alter_id,
        },
        date_variables=DATE_VARS,
    )


def stock_closing(company: Value, as_of: Value) -> bytes:
    """Tally-computed closing stock as of a date (SRS 11.3, GATE-G18)."""
    return envelope(
        tc.STOCK_CLOSING_REPORT,
        {tc.VAR_COMPANY: company, tc.VAR_TO_DATE: as_of},
        date_variables=DATE_VARS,
    )


def ledger_closing(company: Value, as_of: Value) -> bytes:
    """Tally's ledger closing balances as of a date (GATE-G19)."""
    return envelope(
        tc.LEDGER_CLOSING_REPORT,
        {tc.VAR_COMPANY: company, tc.VAR_TO_DATE: as_of},
        date_variables=DATE_VARS,
    )


# --- capture kit only: TallyPrime's built-ins (never used by the Agent, FR-1.4) ----------


def builtin_company_list() -> bytes:
    return envelope(tc.BUILTIN_COMPANY_LIST, {}, request_type=tc.REQUEST_TYPE_COLLECTION)


def builtin_report(name: str, company: Value, date_from: Value, date_to: Value) -> bytes:
    return envelope(
        name,
        {tc.VAR_COMPANY: company, tc.VAR_FROM_DATE: date_from, tc.VAR_TO_DATE: date_to},
        date_variables=DATE_VARS,
    )
