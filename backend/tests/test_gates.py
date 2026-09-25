import re
from pathlib import Path

import pytest

from app.core.gates import (
    COLLECTION_GATES,
    GATE_STATUS_PATH,
    collection_sync_mode,
    gate_passed,
    gate_status,
    load_gate_status,
)

ROOT = Path(__file__).parents[2]
ALL = {f"G{i}": "NOT_TESTED" for i in range(1, 36)}  # G34-G35: D-038


def _with(**changes: str) -> dict[str, str]:
    return {**ALL, **changes}


def test_yaml_has_all_35_gates_not_tested() -> None:
    assert load_gate_status(GATE_STATUS_PATH) == ALL


def test_yaml_matches_validation_gate_doc() -> None:
    doc = (ROOT / "docs/validation-gate.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| (G\d+)\*? \|.*?\| (NOT TESTED|PASSED|FAILED) \|", doc, re.M))
    assert set(rows) == set(ALL)
    assert {g: s.replace(" ", "_") for g, s in rows.items()} == load_gate_status(GATE_STATUS_PATH)


def test_collection_mapping_matches_plan() -> None:
    assert COLLECTION_GATES["LEDGER"] == ("G1", "G5", "G6", "G7", "G10")
    assert COLLECTION_GATES["STOCK_ITEM"] == ("G2", "G5", "G6", "G7", "G10")
    assert COLLECTION_GATES["VOUCHER"] == ("G3", "G5", "G6", "G7", "G8")
    assert COLLECTION_GATES["COST_CENTRE"] == ("G4", "G5", "G6", "G7", "G10")
    for c in ("GROUP", "VOUCHER_TYPE", "COMPANY"):
        assert COLLECTION_GATES[c] == ("G5", "G6", "G7", "G10")


def test_status_and_passed() -> None:
    s = _with(G23="PASSED")
    assert gate_status("G23", s) == "PASSED" and gate_passed("G23", s)
    assert not gate_passed("G1", s)
    with pytest.raises(KeyError):
        gate_status("G99", s)


# Partial: the mode decision. Sync refusing incremental batches is P5 (GATE_NOT_PASSED);
# AC-12's "Full sync only" dashboard indicator comes with the frontend.
@pytest.mark.req_partial("VAL-1.2", "AC-12")
def test_any_failed_forces_full_only_everywhere() -> None:
    s = _with(G7="FAILED")
    for allow in (True, False):
        assert collection_sync_mode("LEDGER", s, allow_unverified=allow) == "FULL_ONLY"


# VAL-1.1 partial throughout: the mode decision; what a release claims is a process check.
@pytest.mark.req_partial("VAL-1.1")
def test_all_passed_is_incremental() -> None:
    s = {g: "PASSED" for g in ALL}
    assert collection_sync_mode("VOUCHER", s, allow_unverified=False) == "INCREMENTAL"


@pytest.mark.req_partial("VAL-1.1")
def test_untested_depends_on_allow_unverified_flag() -> None:
    assert collection_sync_mode("LEDGER", ALL, allow_unverified=True) == "INCREMENTAL"
    assert collection_sync_mode("LEDGER", ALL, allow_unverified=False) == "FULL_ONLY"


@pytest.mark.req_partial("VAL-1.1")
def test_some_passed_is_not_enough_without_the_unverified_flag() -> None:
    """Incremental needs ALL of the collection's rows PASSED, not most of them."""
    s = _with(G1="PASSED", G5="PASSED", G6="PASSED", G7="PASSED")  # G10 still NOT_TESTED
    assert collection_sync_mode("LEDGER", s, allow_unverified=False) == "FULL_ONLY"


def test_gates_of_other_collections_do_not_affect_this_one() -> None:
    # G8 only gates VOUCHER; a failed G8 must not force LEDGER to full-only.
    s = _with(G8="FAILED")
    assert collection_sync_mode("LEDGER", s, allow_unverified=True) == "INCREMENTAL"
    assert collection_sync_mode("VOUCHER", s, allow_unverified=True) == "FULL_ONLY"


def test_default_uses_settings_flag() -> None:
    assert collection_sync_mode("LEDGER") == "INCREMENTAL"  # env=test → flag true (D-029)
