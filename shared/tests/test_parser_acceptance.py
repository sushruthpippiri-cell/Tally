"""P4.9: acceptance checks on the fixtures, and streaming within a memory budget."""

import tracemalloc
from decimal import Decimal

import pytest

from tally_contract.enums import AccountingDirection, CollectionType
from tally_contract.errors import ErrorCode
from tally_contract.parser import parse_collection
from tally_contract.testing import assert_logged
from tally_tools.fixtures import SYNTHETIC, load_spec, parse_fixture

D, C = AccountingDirection.DEBIT, AccountingDirection.CREDIT


def _fixture(case: str):  # type: ignore[no-untyped-def]
    xml = SYNTHETIC / f"{case}.xml"
    return parse_fixture(xml, load_spec(xml))


@pytest.mark.req_partial("AC-34")  # "no analytics query reads amount_raw": P8
def test_sign_normalization_on_raw_tally_entries() -> None:
    """AC-34 (parser half): accounting_direction, is_debit and amount_absolute are correct."""
    vouchers = {v.guid: v for v in _fixture("debit_credit_by_ledger_kind").records}
    expected = {
        "v-k-sale": [
            ("Sharma Traders", D, "1180.00"),
            ("Sales - Retail", C, "1000.00"),
            ("Output GST", C, "180.00"),
        ],
        "v-k-purchase": [
            ("Purchases", D, "500.00"),
            ("Input GST", D, "90.00"),
            ("Kumar Wholesale", C, "590.00"),
        ],
        "v-k-receipt": [("HDFC Current", D, "2000.00"), ("Sharma Traders", C, "2000.00")],
        "v-k-payment": [("Office Rent", D, "750.50"), ("Cash", C, "750.50")],
    }
    for guid, lines in expected.items():
        got = [
            (e.ledger_name, e.amount.accounting_direction, e.amount.amount_absolute)
            for e in vouchers[guid].entries
        ]
        assert got == [(n, d, Decimal(a)) for n, d, a in lines], guid
        for entry in vouchers[guid].entries:
            assert entry.amount.is_debit == (entry.amount.accounting_direction == D)
        assert sum(e.amount.amount_signed for e in vouchers[guid].entries) == 0


@pytest.mark.req("AC-66")
def test_the_malformed_fixture_logs_an_error_and_raises_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = _fixture("malformed")
    assert result.records == [] and result.document_error is not None
    assert result.document_error.code == ErrorCode.PARSE_ERROR
    assert_logged(caplog, "tally_document_error", level="error", code="PARSE_ERROR")


def test_unbalanced_and_foreign_currency_vouchers_are_excluded_with_the_right_code() -> None:
    unbalanced = _fixture("voucher_unbalanced")
    assert [v.guid for v in unbalanced.records] == ["v-bal"]
    assert [(e.guid, e.code) for e in unbalanced.errors] == [
        ("v-unbal", ErrorCode.DEBIT_CREDIT_IMBALANCE)
    ]
    foreign = _fixture("voucher_foreign_currency")
    assert [v.guid for v in foreign.records] == ["v-fx-ok"]
    assert {e.code for e in foreign.errors} == {ErrorCode.PARSE_ERROR}


def _vouchers(n: int) -> bytes:
    row = (
        "<VOUCHER><GUID>v-{i}</GUID><ALTERID>{a}</ALTERID><VOUCHERNUMBER>S-{i}</VOUCHERNUMBER>"
        "<VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><DATE>20240401</DATE>"
        "<NARRATION>Sale number {i} to a regular customer</NARRATION>"
        "<LEDGERENTRY><LEDGERNAME>Customer {c}</LEDGERNAME><LEDGERGUID>l-{c}</LEDGERGUID>"
        "<AMOUNT>-1180.00</AMOUNT><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>"
        "<BILLALLOCATION><NAME>S-{i}</NAME><BILLTYPE>New Ref</BILLTYPE>"
        "<AMOUNT>-1180.00</AMOUNT></BILLALLOCATION></LEDGERENTRY>"
        "<LEDGERENTRY><LEDGERNAME>Sales - Retail</LEDGERNAME><AMOUNT>1000.00</AMOUNT>"
        "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></LEDGERENTRY>"
        "<LEDGERENTRY><LEDGERNAME>Output GST</LEDGERNAME><AMOUNT>180.00</AMOUNT>"
        "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></LEDGERENTRY>"
        "<INVENTORYENTRY><STOCKITEMNAME>Item {s}</STOCKITEMNAME><QUANTITY>10 Nos</QUANTITY>"
        "<RATE>100.00/Nos</RATE><AMOUNT>1000.00</AMOUNT><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
        "</INVENTORYENTRY></VOUCHER>"
    )
    body = "".join(row.format(i=i, a=i + 1, c=i % 300, s=i % 50) for i in range(n))
    return f"<ENVELOPE><TA_VOUCHERS>{body}</TA_VOUCHERS></ENVELOPE>".encode()


def test_5000_vouchers_stream_without_loading_the_document_twice() -> None:
    """Measured 2026-09-27: 5,000 vouchers = 5.4 MB of XML; the parser's own transient memory
    (peak minus the records it returns) was 1.1x the XML, i.e. one decoded copy. Without
    clearing parsed elements it was 4.4x. Budget: 2x."""
    raw = _vouchers(5000)
    tracemalloc.start()
    try:
        result = parse_collection(raw, CollectionType.VOUCHER)
        kept, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(result.records) == 5000 and result.errors == []
    assert peak - kept < 2 * len(raw), f"transient {(peak - kept) / 1e6:.1f} MB"
