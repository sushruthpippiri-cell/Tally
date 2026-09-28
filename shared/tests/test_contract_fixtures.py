"""P4.8: the contract harness - every fixture through the parser, compared with its expected
result (TEST-1.1..1.4). Runs in CI with no Tally. Live captures join in gate-track step G-E."""

from pathlib import Path

import pytest

from tally_contract.testing import assert_logged
from tally_tools.fixtures import (
    FIXTURES,
    SYNTHETIC,
    as_json,
    cases,
    expected_path,
    load_spec,
    parse_fixture,
)

CASES = cases()

# TEST-1.2, as the SRS lists it, and the fixture that covers each item.
TEST_1_2 = {
    "new, modified and cancelled vouchers": ["vouchers_v1", "vouchers_v2_modified"],
    "multiple ledger entries": ["voucher_journal_multiple_entries"],
    "inventory entries": ["voucher_sales_inventory"],
    "bill allocations of every type": ["bill_allocations_all_types"],
    "cost-centre allocations": ["cost_centre_allocations"],
    "missing optional fields": ["missing_optional_fields"],
    "malformed XML": ["malformed"],
    "unexpected structure": ["unexpected_structure"],
    "a three-level group chain": ["groups_three_level_chain"],
    "a group with a missing parent": ["group_missing_parent"],
    "a custom voucher type derived from Sales": ["voucher_types_custom_and_unresolvable"],
    "an unresolvable voucher type": ["voucher_types_custom_and_unresolvable"],
    "opening balances": [
        "ledgers_opening_balances",
        "ledgers_opening_blank",  # GATE-G16 (D-044 #6): blank = zero
        "ledgers_opening_zero",
        "ledgers_opening_absent",  # absent = unavailable
        "stock_items_opening",
    ],
    "stock snapshots": ["stock_snapshots"],
    "debit and credit entries on sales, purchase, receipt, payment and tax ledgers": [
        "debit_credit_by_ledger_kind"
    ],
}


def _id(xml: Path) -> str:
    return xml.relative_to(FIXTURES).as_posix()


@pytest.mark.req("TEST-1.3")
@pytest.mark.req_partial("TEST-1.1")  # compared with the normalized model; database rows: P5
@pytest.mark.parametrize("xml", CASES, ids=_id)
def test_fixture_parses_to_its_expected_result(xml: Path) -> None:
    spec = load_spec(xml)
    assert "expected" in spec, f"run `make update-fixtures FORCE=1` for {_id(xml)} and review"
    assert as_json(parse_fixture(xml, spec)) == spec["expected"]


@pytest.mark.req("TEST-1.2")
def test_every_case_the_srs_lists_has_a_fixture() -> None:
    names = {p.stem for p in SYNTHETIC.glob("*.xml")}
    missing = {item: f for item, fs in TEST_1_2.items() for f in fs if f not in names}
    assert missing == {}


def test_every_fixture_has_exactly_one_expected_file() -> None:
    xmls = {p.stem for p in SYNTHETIC.glob("*.xml")}
    expected = {p.name.removesuffix(".expected.json") for p in SYNTHETIC.glob("*.expected.json")}
    assert xmls == expected
    assert all(expected_path(p).is_file() for p in CASES)


@pytest.mark.req("TEST-1.4")
@pytest.mark.parametrize(
    ("case", "event"),
    [
        ("malformed", "tally_document_error"),
        ("tally_error_tdl_not_loaded", "tally_document_error"),
        ("tally_error_company_not_open", "tally_document_error"),
        ("unexpected_structure", "record_parse_failed"),
        ("voucher_foreign_currency", "record_parse_failed"),
        ("voucher_unbalanced", "record_parse_failed"),
    ],
)
def test_bad_input_is_logged_and_never_raises(
    case: str, event: str, caplog: pytest.LogCaptureFixture
) -> None:
    xml = SYNTHETIC / f"{case}.xml"
    result = parse_fixture(xml, load_spec(xml))  # no exception escapes
    assert result.document_error is not None or result.errors
    assert_logged(caplog, event)


def test_live_captures_join_only_with_a_reviewed_expected_file() -> None:
    """Until step G-E adds <id>.response.expected.json, live captures are not test cases."""
    live = [p for p in CASES if "live" in p.parts]
    for xml in live:
        assert xml.name.endswith(".response.xml")
    assert all("synthetic" in p.parts or p in live for p in CASES)
