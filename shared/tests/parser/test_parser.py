"""P4.4: parsing responses. Nothing raises (TEST-1.4, AC-66); a bad record fails alone
(SYNC-6.5); Tally's own errors are recognised (FR-1.4, AGT-5.3)."""

from datetime import date
from decimal import Decimal

import pytest

from tally_contract.enums import AllocationType, CollectionType
from tally_contract.errors import ErrorCode
from tally_contract.parser import (
    parse_collection,
    parse_info,
    parse_keys,
    parse_ledger_closing,
    parse_stock_closing,
)
from tally_contract.records import GroupRecord, LedgerRecord, VoucherRecord
from tally_contract.testing import assert_logged


def _doc(root: str, body: str) -> bytes:
    return f"<ENVELOPE><{root}>{body}</{root}></ENVELOPE>".encode()


GROUPS = _doc(
    "TA_GROUPS",
    """
    <GROUP><GUID>g-sales</GUID><ALTERID>5</ALTERID><NAME>Sales Accounts</NAME>
      <PARENT>&#4; Primary</PARENT><PARENTGUID></PARENTGUID>
      <RESERVEDNAME>Sales Accounts</RESERVEDNAME>
      <ISREVENUE>Yes</ISREVENUE><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
      <AFFECTSGROSSPROFIT>Yes</AFFECTSGROSSPROFIT></GROUP>
    <GROUP><GUID>g-online</GUID><ALTERID>not-a-number</ALTERID><NAME>Sales - Online</NAME>
      <PARENT>Sales Accounts</PARENT><PARENTGUID>g-sales</PARENTGUID></GROUP>
    <GROUP><GUID>g-market</GUID><ALTERID>9</ALTERID><NAME>Sales - Online - Marketplace</NAME>
      <PARENT>Sales - Online</PARENT><PARENTGUID>g-online</PARENTGUID></GROUP>
    """,
)


@pytest.mark.req_partial("SYNC-6.5")  # stored in sync_errors: P5
def test_one_bad_record_fails_alone_and_the_rest_parse(caplog: pytest.LogCaptureFixture) -> None:
    result = parse_collection(GROUPS, CollectionType.GROUP)
    assert result.ok
    assert [r.guid for r in result.records] == ["g-sales", "g-market"]
    [error] = result.errors
    assert (error.guid, error.code) == ("g-online", ErrorCode.PARSE_ERROR)
    assert "not an integer" in error.message and "Sales - Online" in (error.snippet or "")
    assert_logged(caplog, "record_parse_failed", level="warning", guid="g-online")
    top: GroupRecord = result.records[0]
    assert (top.parent_name, top.parent_guid, top.reserved_name, top.is_revenue) == (
        None,
        None,
        "Sales Accounts",
        True,
    )
    assert result.invalid_characters_removed == 1  # the &#4; before Primary


@pytest.mark.req("AC-66")
@pytest.mark.req_partial("TEST-1.4")  # over every fixture: the P4.8 harness
@pytest.mark.parametrize(
    "raw",
    [
        b"<ENVELOPE><TA_GROUPS><GROUP><GUID>x</GUID>",  # truncated
        b"<ENVELOPE><A></B></ENVELOPE>",  # mismatched
        b"",  # empty
        b"\x00\x01\x02 not xml at all",
        "<ENVELOPE>café</ENVELOPE>".encode("latin-1"),  # not UTF-8
    ],
)
def test_malformed_xml_is_logged_and_never_raises(
    raw: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    result = parse_collection(raw, CollectionType.GROUP)
    assert not result.ok and result.records == []
    assert result.document_error is not None
    assert result.document_error.code == ErrorCode.PARSE_ERROR
    assert_logged(caplog, "tally_document_error", level="error", code="PARSE_ERROR")


def test_a_malformed_tail_discards_the_whole_document() -> None:
    """Never half a response: records before the break are not returned either."""
    raw = GROUPS.replace(b"</ENVELOPE>", b"<BROKEN></ENVELOPE>")
    result = parse_collection(raw, CollectionType.GROUP)
    assert result.records == [] and result.document_error is not None


@pytest.mark.req_partial("FR-1.4")  # the Agent reporting it and never falling back: P7
def test_report_not_found_means_tdl_not_loaded() -> None:
    raw = b"<RESPONSE><LINEERROR>Could not find Report 'TA_Ledgers'!</LINEERROR></RESPONSE>"
    result = parse_collection(raw, CollectionType.LEDGER)
    assert result.document_error is not None
    assert result.document_error.code == ErrorCode.TDL_NOT_LOADED


def test_company_not_open_means_company_not_loaded() -> None:
    raw = b"<RESPONSE><LINEERROR>Could not set 'SVCurrentCompany' to 'X'</LINEERROR></RESPONSE>"
    assert parse_info(raw).document_error.code == ErrorCode.COMPANY_NOT_LOADED  # type: ignore[union-attr]


def test_any_other_tally_error_is_a_document_error_not_data() -> None:
    raw = b"<RESPONSE><LINEERROR>Something unexpected</LINEERROR></RESPONSE>"
    error = parse_keys(raw).document_error
    assert error is not None and error.code == ErrorCode.PARSE_ERROR
    assert "Something unexpected" in error.message


def test_info_gives_tdl_version_and_the_company_guid() -> None:
    raw = _doc(
        "TA_INFO",
        "<INFO><TDLVERSION>0.1.0</TDLVERSION><COMPANYGUID>c-1</COMPANYGUID>"
        "<COMPANYNAME>Sharma &amp; Sons</COMPANYNAME></INFO>",
    )
    [info] = parse_info(raw).records
    assert (info.tdl_version, info.company_guid, info.company_name) == (
        "0.1.0",
        "c-1",
        "Sharma & Sons",
    )
    empty = _doc(
        "TA_INFO", "<INFO><TDLVERSION>0.1.0</TDLVERSION><COMPANYGUID></COMPANYGUID></INFO>"
    )
    assert parse_info(empty).errors  # no GUID: the company is not visible


def test_company_ledger_and_masters() -> None:
    company = parse_collection(
        _doc(
            "TA_COMPANY",
            """<COMPANY><GUID>c-1</GUID><ALTERID>1</ALTERID>
        <NAME>Test Co</NAME><BOOKSFROM>20240401</BOOKSFROM><FYSTART>20240401</FYSTART>
        <LASTMASTERALTERID>120</LASTMASTERALTERID><LASTVOUCHERALTERID></LASTVOUCHERALTERID></COMPANY>""",
        ),
        CollectionType.COMPANY,
    ).records[0]
    assert (company.books_from, company.last_master_alter_id, company.last_voucher_alter_id) == (
        date(2024, 4, 1),
        120,
        None,
    )
    ledgers = parse_collection(
        _doc(
            "TA_LEDGERS",
            """
        <LEDGER><GUID>l-1</GUID><ALTERID>7</ALTERID><NAME>Sharma Traders</NAME>
          <PARENT>Sundry Debtors</PARENT><PARENTGUID>g-sd</PARENTGUID><ISBILLWISE>Yes</ISBILLWISE>
          <OPENINGBALANCE>-5000.00</OPENINGBALANCE><ISINACTIVE></ISINACTIVE>
          <OPENINGBILL><NAME>INV-9</NAME><BILLDATE>20240315</BILLDATE><DUEDATE></DUEDATE>
            <AMOUNT>-5000.00</AMOUNT></OPENINGBILL></LEDGER>
        <LEDGER><GUID>l-2</GUID><ALTERID>8</ALTERID><NAME>Capital</NAME>
          <PARENT>Capital Account</PARENT><OPENINGBALANCE>25000</OPENINGBALANCE></LEDGER>
        <LEDGER><GUID>l-3</GUID><ALTERID>9</ALTERID><NAME>Cash</NAME><PARENT>Cash-in-Hand</PARENT>
        </LEDGER>""",
        ),
        CollectionType.LEDGER,
    )
    customer, capital, cash = ledgers.records
    assert isinstance(customer, LedgerRecord)
    assert customer.opening_balance is not None and customer.opening_balance.is_debit
    assert customer.opening_balance.amount_signed == Decimal(
        "5000.00"
    )  # GATE-G16: negative = debit
    assert customer.opening_bills[0].reference_name == "INV-9"
    assert customer.is_inactive is None  # GATE-G29 not exported
    assert capital.opening_balance.accounting_direction == "CREDIT"
    assert cash.opening_balance is None
    item = parse_collection(
        _doc(
            "TA_STOCKITEMS",
            """<STOCK_ITEM><GUID>s-1</GUID><ALTERID>3</ALTERID>
        <NAME>Soap</NAME><BASEUNIT>Nos</BASEUNIT><ALTERNATEUNIT>Box</ALTERNATEUNIT>
        <CONVERSION>12</CONVERSION><DENOMINATOR>1</DENOMINATOR><OPENINGQTY>24 Nos</OPENINGQTY>
        <OPENINGVALUE>-480.00</OPENINGVALUE><OPENINGRATE>20.00/Nos</OPENINGRATE></STOCK_ITEM>""",
        ),
        CollectionType.STOCK_ITEM,
    ).records[0]
    assert (item.conversion, item.opening_quantity, item.opening_value, item.opening_rate) == (
        Decimal("12"),
        Decimal("24"),
        Decimal("480.00"),
        Decimal("20.00"),
    )


VOUCHER = _doc(
    "TA_VOUCHERS",
    """
<VOUCHER><GUID>v-1</GUID><ALTERID>41</ALTERID><VOUCHERNUMBER>S/1</VOUCHERNUMBER>
  <VOUCHERTYPENAME>POS Invoice</VOUCHERTYPENAME><VOUCHERTYPEGUID>vt-pos</VOUCHERTYPEGUID>
  <DATE>20240401</DATE><NARRATION>Counter sale</NARRATION><ISCANCELLED>No</ISCANCELLED>
  <LEDGERENTRY><LEDGERNAME>Sharma Traders</LEDGERNAME><LEDGERGUID>l-1</LEDGERGUID>
    <AMOUNT>-1180.00</AMOUNT><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <BILLALLOCATION><NAME>S/1</NAME><BILLTYPE>New Ref</BILLTYPE><DUEDATE>20240501</DUEDATE>
      <AMOUNT>-1180.00</AMOUNT></BILLALLOCATION></LEDGERENTRY>
  <LEDGERENTRY><LEDGERNAME>Sales</LEDGERNAME><LEDGERGUID></LEDGERGUID>
    <AMOUNT>1000.00</AMOUNT><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
    <COSTCATEGORY><COSTCENTREALLOCATION><NAME>Retail</NAME><COSTCENTREGUID>cc-1</COSTCENTREGUID>
      <AMOUNT>1000.00</AMOUNT></COSTCENTREALLOCATION></COSTCATEGORY></LEDGERENTRY>
  <LEDGERENTRY><LEDGERNAME>Output GST</LEDGERNAME><AMOUNT>180.00</AMOUNT>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></LEDGERENTRY>
  <INVENTORYENTRY><STOCKITEMNAME>Soap</STOCKITEMNAME><STOCKITEMGUID>s-1</STOCKITEMGUID>
    <QUANTITY>10 Nos</QUANTITY><RATE>100.00/Nos</RATE><AMOUNT>1000.00</AMOUNT>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></INVENTORYENTRY>
</VOUCHER>
<VOUCHER><GUID>v-2</GUID><ALTERID>42</ALTERID><VOUCHERTYPENAME>Receipt</VOUCHERTYPENAME>
  <DATE>20240402</DATE><ISCANCELLED>Yes</ISCANCELLED>
  <LEDGERENTRY><LEDGERNAME>Cash</LEDGERNAME><AMOUNT>-500</AMOUNT><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
  </LEDGERENTRY>
</VOUCHER>""",
)


def test_voucher_with_entries_bills_cost_centres_and_items() -> None:
    result = parse_collection(VOUCHER, CollectionType.VOUCHER)
    [voucher] = result.records
    assert isinstance(voucher, VoucherRecord)
    assert (voucher.voucher_type_name, voucher.voucher_date, voucher.is_cancelled) == (
        "POS Invoice",
        date(2024, 4, 1),
        False,
    )
    customer, sales, tax = voucher.entries
    assert [e.line_sequence for e in voucher.entries] == [1, 2, 3]
    assert (customer.amount.accounting_direction, customer.amount.amount_signed) == (
        "DEBIT",
        Decimal("1180.00"),
    )
    assert (sales.ledger_guid, sales.amount.amount_signed) == (
        None,
        Decimal("-1000.00"),
    )  # D-002 fallback
    assert customer.bill_allocations[0].allocation_type == AllocationType.NEW_REF
    assert sales.cost_centre_allocations[0].amount_absolute == Decimal("1000.00")
    [item] = voucher.items
    assert (item.quantity, item.unit, item.rate, item.amount.accounting_direction) == (
        Decimal("10"),
        "Nos",
        Decimal("100.00"),
        "CREDIT",
    )
    # v-2: its indicators disagree (-500 is a debit, ISDEEMEDPOSITIVE says credit):
    # rejected, never guessed.
    [error] = result.errors
    assert error.guid == "v-2" and "disagree" in error.message


def test_unknown_bill_type_is_unsupported_not_guessed() -> None:
    raw = VOUCHER.replace(b"New Ref", b"Something New")
    bill = parse_collection(raw, CollectionType.VOUCHER).records[0].entries[0].bill_allocations[0]
    assert (bill.allocation_type_raw, bill.allocation_type) == (
        "Something New",
        AllocationType.UNSUPPORTED,
    )


def test_keys_and_closing_balances() -> None:
    keys = parse_keys(_doc("TA_LEDGERSKEYS", "<KEY><GUID>l-1</GUID><ALTERID>7</ALTERID></KEY>"))
    assert [(k.guid, k.alter_id) for k in keys.records] == [("l-1", 7)]
    stock = parse_stock_closing(
        _doc(
            "TA_STOCKCLOSING",
            """<STOCK_CLOSING><GUID>s-1</GUID>
        <NAME>Soap</NAME><ASOFDATE>20250331</ASOFDATE>
        <CLOSINGQTY>14 Nos</CLOSINGQTY></STOCK_CLOSING>""",
        )
    )
    assert (stock.records[0].closing_quantity, stock.records[0].unit) == (Decimal("14"), "Nos")
    ledger = parse_ledger_closing(
        _doc(
            "TA_LEDGERCLOSING",
            """<LEDGER_CLOSING><GUID>l-1</GUID>
        <NAME>Cash</NAME><ASOFDATE>20250331</ASOFDATE><CLOSINGBALANCE>-2500.00</CLOSINGBALANCE>
        </LEDGER_CLOSING>""",
        )
    )
    assert ledger.records[0].balance.accounting_direction == "DEBIT"


def test_a_crashing_builder_is_still_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    from tally_contract.parser import document

    def explode(_: object) -> None:
        raise RuntimeError("bug")

    result = document.parse(GROUPS, "GROUP", explode)
    assert result.document_error is not None and "RuntimeError" in result.document_error.message
