from pathlib import Path

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
"""


def test_requirement_ids_extracts_prefixed_ids_in_order() -> None:
    assert requirement_ids(SAMPLE_SRS) == ["SYNC-3.2", "ACC-DATA-1", "FR-STK-12", "AC-06"]


def test_requirement_ids_are_deduplicated() -> None:
    assert requirement_ids("AC-06 AC-06 SEC-1.7") == ["AC-06", "SEC-1.7"]


def test_markers_by_id_reads_sync_and_async_tests(tmp_path: Path) -> None:
    (tmp_path / "shared/tests").mkdir(parents=True)
    (tmp_path / "shared/tests/test_sample.py").write_text(SAMPLE_TEST)
    found = markers_by_id(tmp_path, dirs=("shared/tests",))
    assert found["SYNC-3.2"] == ["shared/tests/test_sample.py::test_stale"]
    assert found["AC-06"] == ["shared/tests/test_sample.py::test_stale"]
    assert found["BOGUS-9"] == ["shared/tests/test_sample.py::test_async_marked"]


def test_render_lists_covered_missing_and_unknown() -> None:
    out = render(["SYNC-3.2", "AC-06"], {"SYNC-3.2": ["t.py::test_x"], "BOGUS-9": ["t.py::test_y"]})
    assert "| SYNC-3.2 | t.py::test_x |" in out
    assert "Covered by at least one test: **1**" in out
    assert "AC-06" in out.split("## Not covered yet")[1]
    assert "BOGUS-9" in out.split("## Marked in tests but not found in the SRS")[1]


def test_render_handles_full_coverage() -> None:
    out = render(["AC-06"], {"AC-06": ["t.py::test_x"]})
    assert "_none_" in out and "Not covered yet: **0**" in out


def test_module_paths_resolve_to_the_repo() -> None:
    from tally_tools.traceability import DEST, ROOT, SRS

    assert (ROOT / "pyproject.toml").is_file()
    assert SRS.is_file() and DEST.parent.is_dir()
