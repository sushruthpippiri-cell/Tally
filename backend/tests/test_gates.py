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
ALL = {f"G{i}": "NOT_TESTED" for i in range(1, 34)}


def _with(**changes: str) -> dict[str, str]:
    return {**ALL, **changes}


def test_yaml_has_all_33_gates_not_tested() -> None:
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


@pytest.mark.req("VAL-1.2")
def test_any_failed_forces_full_only_everywhere() -> None:
    s = _with(G7="FAILED")
    for allow in (True, False):
        assert collection_sync_mode("LEDGER", s, allow_unverified=allow) == "FULL_ONLY"


@pytest.mark.req("VAL-1.1")
def test_all_passed_is_incremental() -> None:
    s = {g: "PASSED" for g in ALL}
    assert collection_sync_mode("VOUCHER", s, allow_unverified=False) == "INCREMENTAL"


@pytest.mark.req("VAL-1.1", "AC-12")
def test_untested_depends_on_allow_unverified_flag() -> None:
    assert collection_sync_mode("LEDGER", ALL, allow_unverified=True) == "INCREMENTAL"
    assert collection_sync_mode("LEDGER", ALL, allow_unverified=False) == "FULL_ONLY"


def test_gates_of_other_collections_do_not_affect_this_one() -> None:
    # G8 only gates VOUCHER; a failed G8 must not force LEDGER to full-only.
    s = _with(G8="FAILED")
    assert collection_sync_mode("LEDGER", s, allow_unverified=True) == "INCREMENTAL"
    assert collection_sync_mode("VOUCHER", s, allow_unverified=True) == "FULL_ONLY"


def test_default_uses_settings_flag() -> None:
    assert collection_sync_mode("LEDGER") == "INCREMENTAL"  # env=test → flag true (D-029)
