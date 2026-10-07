from pathlib import Path

from tally_tools import traceability
from tally_tools.traceability import markers_by_id, render, requirement_ids

SAMPLE_SRS = """# 6. Synchronization
```text
SYNC-3.2   Incoming lower than stored: rejected
ACC-DATA-1 Analytics read normalized fields
FR-STK-12  Never sold
AC-06      Stale record
```
"""
SAMPLE_TEST = """
import pytest

@pytest.mark.req("SYNC-3.2", "AC-06")
def test_stale() -> None: ...

@pytest.mark.req("BOGUS-9")
async def test_async_marked() -> None: ...

def test_unmarked() -> None: ...

@pytest.mark.req_partial("FR-STK-12", "SYNC-3.2")
def test_part() -> None: ...
"""


def test_requirement_ids_extracts_prefixed_ids_in_order() -> None:
    assert requirement_ids(SAMPLE_SRS) == ["SYNC-3.2", "ACC-DATA-1", "FR-STK-12", "AC-06"]


def test_requirement_ids_are_deduplicated() -> None:
    assert requirement_ids("AC-06 AC-06 SEC-1.7") == ["AC-06", "SEC-1.7"]


def test_markers_by_id_reads_sync_and_async_tests(tmp_path: Path) -> None:
    (tmp_path / "shared/tests").mkdir(parents=True)
    (tmp_path / "shared/tests/test_sample.py").write_text(SAMPLE_TEST, encoding="utf-8")
    found = markers_by_id(tmp_path, dirs=("shared/tests",))
    assert found["SYNC-3.2"] == ["shared/tests/test_sample.py::test_stale"]
    assert found["AC-06"] == ["shared/tests/test_sample.py::test_stale"]
    assert found["BOGUS-9"] == ["shared/tests/test_sample.py::test_async_marked"]
    assert "FR-STK-12" not in found  # req_partial is a different marker


def test_markers_by_id_reads_partial_markers_separately(tmp_path: Path) -> None:
    (tmp_path / "shared/tests").mkdir(parents=True)
    (tmp_path / "shared/tests/test_sample.py").write_text(SAMPLE_TEST, encoding="utf-8")
    partial = markers_by_id(tmp_path, dirs=("shared/tests",), marker="req_partial")
    assert partial == {
        "FR-STK-12": ["shared/tests/test_sample.py::test_part"],
        "SYNC-3.2": ["shared/tests/test_sample.py::test_part"],
    }


def test_render_lists_partial_coverage_separately_and_never_as_covered() -> None:
    out = render(
        ["SYNC-3.2", "FR-STK-12", "AC-06"],
        {"SYNC-3.2": ["t.py::test_x"]},
        {"FR-STK-12": ["t.py::test_p"], "SYNC-3.2": ["t.py::test_p"]},
    )
    assert "Fully covered by at least one test: **1**" in out
    assert "Partially covered only: **1**" in out and "Not accounted for at all: **1**" in out
    covered = out.split("## Covered")[1].split("## Partially covered")[0]
    partial = out.split("## Partially covered")[1].split("## Not accounted for at all")[0]
    missing = out.split("## Not accounted for at all")[1]
    assert "FR-STK-12" not in covered and "| FR-STK-12 | t.py::test_p |" in partial
    assert "SYNC-3.2" not in partial  # has a full test
    assert "FR-STK-12" not in missing and "AC-06" in missing


def test_render_lists_covered_missing_and_unknown() -> None:
    out = render(
        ["SYNC-3.2", "AC-06"], {"SYNC-3.2": ["t.py::test_x"], "BOGUS-9": ["t.py::test_y"]}, {}
    )
    assert "| SYNC-3.2 | t.py::test_x |" in out
    assert "Fully covered by at least one test: **1**" in out
    assert "AC-06" in out.split("## Not accounted for at all")[1]
    assert "BOGUS-9" in out.split("## Marked in tests but not found in the SRS")[1]


def test_render_handles_full_coverage() -> None:
    out = render(["AC-06"], {"AC-06": ["t.py::test_x"]}, {})
    assert "_none_" in out and "Not accounted for at all: **0**" in out


def test_module_paths_resolve_to_the_repo() -> None:
    from tally_tools.traceability import DEST, ROOT, SRS

    assert (ROOT / "pyproject.toml").is_file()
    assert SRS.is_file() and DEST.parent.is_dir()


# --- P16.9: the gate, and what counts as tracked ----------------------------------------


def test_a_group_reference_is_not_a_requirement() -> None:
    """The SRS writes "FR-1.x" and "SEC-1.x" in its own architecture tables. Without the
    lookahead the regex takes "FR-1" out of them, and 28 section headings were being reported
    as uncovered requirements - noise that made the real gaps hard to see (P16.9)."""
    ids = traceability.requirement_ids("FR-1.x TDL Controlled\nSEC-1.x RBAC\nFR-1.4 real\n")
    assert ids == ["FR-1.4"]


def test_a_requirement_id_at_the_end_of_a_sentence_still_counts() -> None:
    """The lookahead must not reject an id followed by a full stop."""
    assert traceability.requirement_ids("as SEC-1.13. And ACC-DATA-1, plus AC-65)") == [
        "SEC-1.13",
        "ACC-DATA-1",
        "AC-65",
    ]


MANUAL_TABLE = """# Manual verification

| ID | Why it cannot be a test | How it is verified | Blocked on |
|---|---|---|---|
| NFR-UI-1 | a layout requirement | Playwright at 360 px | - |
| BKP-1.1 | a provider's configuration | the runbook lists what must hold | Hosting |
| AC-64 | a measurement | the performance suite | The benchmark machine |
"""


def test_manual_entries_tells_verified_from_blocked(tmp_path: Path) -> None:
    path = tmp_path / "manual-verification.md"
    path.write_text(MANUAL_TABLE, encoding="utf-8")
    entries = traceability.manual_entries(path)
    assert entries["NFR-UI-1"] == ("a layout requirement", "")  # "-" means verified
    assert entries["BKP-1.1"][1] == "Hosting"
    assert entries["AC-64"][1] == "The benchmark machine"


def test_manual_entries_ignores_prose_and_other_tables(tmp_path: Path) -> None:
    path = tmp_path / "manual-verification.md"
    path.write_text(
        MANUAL_TABLE + "\n| Not an id | some | other | table |\n| 1 | 2 | 3 | 4 |\n",
        encoding="utf-8",
    )
    assert set(traceability.manual_entries(path)) == {"NFR-UI-1", "BKP-1.1", "AC-64"}


def test_the_report_keeps_covered_verified_and_blocked_apart() -> None:
    ids = ["ACC-1.1", "NFR-UI-1", "BKP-1.1", "TZ-1.1", "SEC-1.1"]
    tests = {"ACC-1.1": ["tests/test_a.py::test_a"]}
    partial = {"TZ-1.1": ["tests/test_b.py::test_b"]}
    manual = {"NFR-UI-1": ("a layout requirement", ""), "BKP-1.1": ("config", "Hosting")}
    report = traceability.render(ids, tests, partial, manual)
    assert "Fully covered by at least one test: **1**" in report
    assert "Verified by hand: **1**" in report
    assert "not yet verified** (blocked): **1**" in report
    assert "Partially covered only: **1**" in report
    # SEC-1.1 has nothing at all: that is what the gate fails on.
    assert "## Not accounted for at all" in report
    assert "SEC-1.1" in report.split("## Not accounted for at all")[1]
    # A partial test is never counted as covered (CLAUDE.md).
    assert "TZ-1.1" not in report.split("## Covered")[1].split("##")[0]
