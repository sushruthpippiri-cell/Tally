"""P4.6: user-defined fields (DR-UDF-1..4). Regenerate the golden include with UPDATE_GOLDEN=1."""

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from tally_contract.enums import CollectionType
from tally_contract.errors import ErrorCode
from tally_contract.parser import parse_collection
from tally_contract.testing import assert_logged
from tally_contract.udf import UDF_LINES, UdfMapping, UdfReader, UdfType, generate_tdl

ROOT = Path(__file__).parents[2]
GOLDEN = Path(__file__).parent / "golden" / "udf" / "include.tdl"
TDL = (ROOT / "tdl" / "TallyAnalytics.tdl").read_text(encoding="utf-8")

MAPPINGS = [
    UdfMapping(
        collection_type=CollectionType.VOUCHER,
        tally_field="OrderRef",
        field_key="order_ref",
        data_type=UdfType.TEXT,
    ),
    UdfMapping(
        collection_type=CollectionType.LEDGER,
        tally_field="CreditLimitDays",
        field_key="credit_days",
        data_type=UdfType.NUMBER,
    ),
    UdfMapping(
        collection_type=CollectionType.LEDGER,
        tally_field="KYCDate",
        field_key="kyc_date",
        data_type=UdfType.DATE,
    ),
    UdfMapping(
        collection_type=CollectionType.LEDGER,
        tally_field="IsKeyAccount",
        field_key="key_account",
        data_type=UdfType.LOGICAL,
    ),
]


@pytest.mark.req_partial("DR-UDF-4")  # served to the Owner by the P5 endpoint
def test_the_include_is_generated_from_mappings_deterministically() -> None:
    generated = generate_tdl(MAPPINGS)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(generated, encoding="utf-8", newline="\n")
    assert generated == GOLDEN.read_text(encoding="utf-8")
    assert generate_tdl(list(reversed(MAPPINGS))) == generated
    assert generated.count(";; GATE-G22") == len(MAPPINGS)


def test_the_include_extends_lines_that_exist_in_our_tdl() -> None:
    for line in UDF_LINES.values():
        assert f"[Line: {line}]" in TDL


@pytest.mark.req_partial("DR-UDF-1")  # adding mappings (Owner/Admin API and UI): P5
def test_nothing_is_extracted_without_mappings() -> None:
    assert "UDF" not in TDL
    assert "[#Line" not in generate_tdl([])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tally_field", "Region\n[Report: Evil]"),
        ("tally_field", "$$SysName"),
        ("tally_field", "Bad Name"),
        ("field_key", "OrderRef"),
        ("field_key", "order-ref"),
        ("collection_type", "GROUP"),
    ],
)
def test_mappings_that_could_inject_tdl_are_rejected(field: str, value: str) -> None:
    good = {
        "collection_type": "VOUCHER",
        "tally_field": "OrderRef",
        "field_key": "order_ref",
        "data_type": "TEXT",
    }
    with pytest.raises(ValidationError):
        UdfMapping.model_validate(good | {field: value})


def test_a_key_mapped_twice_is_rejected() -> None:
    with pytest.raises(ValueError, match="twice"):
        generate_tdl([MAPPINGS[0], MAPPINGS[0]])


LEDGERS = b"""<ENVELOPE><TA_LEDGERS>
<LEDGER><GUID>l-1</GUID><ALTERID>1</ALTERID><NAME>Sharma</NAME><PARENT>Sundry Debtors</PARENT>
  <UDF_CREDIT_DAYS>45</UDF_CREDIT_DAYS><UDF_KYC_DATE>20240401</UDF_KYC_DATE>
  <UDF_KEY_ACCOUNT>Yes</UDF_KEY_ACCOUNT></LEDGER>
<LEDGER><GUID>l-2</GUID><ALTERID>2</ALTERID><NAME>Gupta</NAME><PARENT>Sundry Debtors</PARENT>
  <UDF_CREDIT_DAYS></UDF_CREDIT_DAYS><UDF_KEY_ACCOUNT>No</UDF_KEY_ACCOUNT></LEDGER>
<LEDGER><GUID>l-3</GUID><ALTERID>3</ALTERID><NAME>Mehta</NAME><PARENT>Sundry Debtors</PARENT>
  <UDF_KEY_ACCOUNT>No</UDF_KEY_ACCOUNT></LEDGER>
<LEDGER><GUID>l-4</GUID><ALTERID>4</ALTERID><NAME>Kumar</NAME><PARENT>Sundry Creditors</PARENT>
  <UDF_CREDIT_DAYS>forty</UDF_CREDIT_DAYS><UDF_KEY_ACCOUNT>No</UDF_KEY_ACCOUNT></LEDGER>
</TA_LEDGERS></ENVELOPE>"""


@pytest.mark.req_partial("DR-UDF-2")  # stored, shown in drill-down and exports: P5, P14
def test_values_are_typed_into_custom_fields() -> None:
    result = parse_collection(LEDGERS, CollectionType.LEDGER, UdfReader(MAPPINGS))
    sharma, gupta, mehta = result.records
    assert sharma.custom_fields == {
        "credit_days": Decimal("45"),
        "kyc_date": date(2024, 4, 1),
        "key_account": True,
    }
    assert gupta.custom_fields == {"credit_days": None, "kyc_date": None, "key_account": False}
    assert mehta.custom_fields["credit_days"] is None
    # A value that is not what the mapping says fails that record, never guessed.
    [error] = result.errors
    assert error.guid == "l-4" and "not a number" in error.message


@pytest.mark.req_partial("DR-UDF-3")  # the null stored and the sync log entry: P5
def test_a_missing_field_is_none_and_logged_once_per_run(caplog: pytest.LogCaptureFixture) -> None:
    reader = UdfReader(MAPPINGS)
    for _ in range(3):  # three responses in one run
        parse_collection(LEDGERS, CollectionType.LEDGER, reader)
    warnings = [
        r
        for r in caplog.records
        if isinstance(r.msg, dict) and r.msg.get("event") == "udf_not_found"
    ]
    # Two fields go missing 9 times in all (3 records x 3 responses); each is logged once.
    assert sorted(w.msg["field_key"] for w in warnings) == ["credit_days", "kyc_date"]
    assert_logged(caplog, "udf_not_found", level="warning", code=ErrorCode.UDF_NOT_FOUND.value)
    # A new run warns again.
    parse_collection(LEDGERS, CollectionType.LEDGER, UdfReader(MAPPINGS))
    assert (
        len(
            [
                r
                for r in caplog.records
                if isinstance(r.msg, dict) and r.msg.get("event") == "udf_not_found"
            ]
        )
        == 4
    )


def test_other_collections_are_untouched() -> None:
    result = parse_collection(LEDGERS, CollectionType.LEDGER, UdfReader(MAPPINGS[:1]))
    assert all(r.custom_fields == {} for r in result.records)
    assert re.search(r"TA_UDF_VOUCHER_order_ref", generate_tdl(MAPPINGS[:1]))
