"""P4.2: the TDL agrees with tally_constants, and every collection meets FR-1.2."""

import re
from pathlib import Path

import pytest

from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType

TDL = Path(__file__).parents[2] / "tdl"
FULL = (TDL / "TallyAnalytics.tdl").read_text(encoding="utf-8")
MINIMAL = (TDL / "TA_Minimal.tdl").read_text(encoding="utf-8")


def _block(text: str, kind: str, name: str) -> str:
    """The body of `[kind: name]` up to the next definition."""
    match = re.search(rf"^\[{kind}: {re.escape(name)}\]\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert match, f"[{kind}: {name}] not found"
    return match.group(1)


def _attr(block: str, attr: str) -> str:
    match = re.search(rf"^\s*{attr}\s*:\s*(.+?)\s*(;;.*)?$", block, re.M)
    assert match, f"{attr} missing"
    return match.group(1)


def _info(text: str) -> str:
    return text[text.index(";; ==== BEGIN TA_INFO") : text.index(";; ==== END TA_INFO ====")]


def test_minimal_tdl_is_exactly_the_info_section_of_the_full_one() -> None:
    assert _info(MINIMAL) == _info(FULL)
    assert "[Report: TA_Info]" in MINIMAL and MINIMAL.count("[Report:") == 1


def test_tdl_version_matches_the_contract() -> None:
    for text in (FULL, MINIMAL):
        assert re.search(rf'TA_TDLVersion\s*:\s*"{re.escape(tc.TDL_VERSION)}"', text)


def _line_of(report: str) -> tuple[str, str]:
    part = _block(FULL, "Part", report)
    repeat = re.search(r"Repeat\s*:\s*(\w+)\s*:\s*(\w+)", part)
    line = repeat.group(1) if repeat else _attr(part, "Line")
    return line, (repeat.group(2) if repeat else "")


@pytest.mark.req_partial(
    "FR-1.1", "FR-1.2", "FR-1.3"
)  # drafts: live Tally proves them (G1-G7, G21)
@pytest.mark.parametrize("collection", list(tc.REPORTS), ids=str)
def test_every_collection_has_guid_alterid_window_and_a_key_only_report(
    collection: CollectionType,
) -> None:
    report = tc.REPORTS[collection]
    line, coll = _line_of(report)
    fields = _attr(_block(FULL, "Line", line), "Fields")
    assert "TA_Guid" in fields and "TA_AlterId" in fields
    assert _attr(_block(FULL, "Line", line), "XMLTag") == f'"{tc.RECORD_TAGS[report]}"'
    filters = _attr(_block(FULL, "Collection", coll), "Filter")
    assert "TA_InAlterIdWindow" in filters or collection == CollectionType.COMPANY
    key_line, key_coll = _line_of(tc.KEY_REPORTS[collection])
    assert (key_line, key_coll) == ("TA_Key", coll)  # same rows, GUID + ALTERID only


def test_every_report_the_contract_names_exists_with_its_record_tag() -> None:
    for report, tag in tc.RECORD_TAGS.items():
        assert f"[Report: {report}]" in FULL, report
        line, _ = _line_of(report)
        assert _attr(_block(FULL, "Line", line), "XMLTag") == f'"{tag}"', report


def test_alter_id_window_variables_match_the_request_builder() -> None:
    for var in (tc.VAR_FROM_ALTER_ID, tc.VAR_TO_ALTER_ID):
        assert f"[Variable: {var}]" in FULL
        assert f"##{var}" in _block(FULL, "System", "Formula") or f"##{var}" in FULL


def test_vouchers_exclude_non_accounting_and_optional_vouchers() -> None:
    """SRS 1.3: no orders or inventory-only vouchers (GATE-G34)."""
    assert "TA_IsAccountingVoucher" in _attr(
        _block(FULL, "Collection", "TA_VouchersColl"), "Filter"
    )


def test_no_gst_tax_detail_is_extracted() -> None:
    """D-037: GST analytics are out of v1."""
    for word in ("HSN", "GSTRate", "CGST", "SGST", "IGST", "TaxClassification"):
        assert word not in FULL


def test_every_tally_field_formula_is_gate_tagged_or_trivially_ours() -> None:
    """Rule 15: Tally-side methods other than plain names/numbers carry a GATE tag."""
    untagged = []
    for m in re.finditer(r"^\s*Set As\s*:\s*(.+)$", FULL, re.M):
        formula = m.group(1)
        if ";; GATE-G" in formula or formula.startswith("@@"):
            continue
        if re.fullmatch(
            r"\$(Name|VoucherNumber|VoucherTypeName|Narration|LedgerName|StockItemName"
            r"|IsBillWiseOn|\$String:\$IsBillWiseOn)\s*",
            formula,
        ):
            continue
        untagged.append(formula)
    assert untagged == []


@pytest.mark.parametrize("collection", list(tc.REPORTS), ids=str)
def test_a_key_list_and_its_data_pull_share_one_collection_and_filter(
    collection: CollectionType,
) -> None:
    """D-041 #2 (owner): a key list may only be compared with the pull it mirrors. Both reports
    repeat the one named Collection, so the filter (G34 for vouchers) is the same object; the
    key Part adds no filter or collection of its own."""
    _, data_coll = _line_of(tc.REPORTS[collection])
    _, key_coll = _line_of(tc.KEY_REPORTS[collection])
    assert key_coll == data_coll
    assert FULL.count(f"[Collection: {data_coll}]") == 1  # one definition, no look-alike copy
    key_part = _block(FULL, "Part", tc.KEY_REPORTS[collection])
    assert "Filter" not in key_part and "Collection" not in key_part
    if collection == CollectionType.VOUCHER:
        assert "TA_IsAccountingVoucher" in _attr(_block(FULL, "Collection", key_coll), "Filter")


def test_reconciliation_totals_add_up_the_sync_voucher_collection_less_cancelled() -> None:
    """D-048 #4-5: the totals take their vouchers from the sync's own Collection (same G34
    filter), so they cannot catch a wrong filter; that is LEDGER_BALANCE's job. Cancelled
    vouchers are left out, as ACTIVE-only analytics leave them out."""
    totals = _block(FULL, "Collection", "TA_ReconTotalsColl")
    assert _attr(totals, "Source Collection") == "TA_ReconVouchersColl"
    assert _attr(totals, "Walk") == "AllLedgerEntries"
    vouchers = _block(FULL, "Collection", "TA_ReconVouchersColl")
    assert _attr(vouchers, "Source Collection") == "TA_VouchersColl"
    assert _attr(vouchers, "Filter") == "TA_IsNotCancelled"
    assert "TA_IsNotCancelled : NOT $IsCancelled" in FULL
