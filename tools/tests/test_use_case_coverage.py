"""docs/use-case-coverage.md stays true: every SRS Section 20 use case has a row, and every test
the map names still exists (P16.7, TEST-5.1)."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SRS = (ROOT / "docs/srs/SRS_v7_3.md").read_text(encoding="utf-8")
MAP = (ROOT / "docs/use-case-coverage.md").read_text(encoding="utf-8")
REFERENCE = re.compile(r"`((?:backend|frontend|tools|agent|shared)/[^`:]+)::([^`]+)`")


def _section_20() -> str:
    start = SRS.index("# 20. Use Cases")
    return SRS[start : SRS.index("# 21. Technology Stack")]


def test_every_use_case_in_the_srs_has_a_row_and_none_is_invented() -> None:
    in_srs = set(re.findall(r"^(UC-\d+) ", _section_20(), re.MULTILINE))
    in_map = set(re.findall(r"^\| (UC-\d+) ", MAP, re.MULTILINE))
    assert len(in_srs) == 14
    assert in_map == in_srs


def test_every_test_the_map_names_exists() -> None:
    missing = []
    for path, name in REFERENCE.findall(MAP):
        file = ROOT / path
        if not file.is_file() or name not in file.read_text(encoding="utf-8"):
            missing.append(f"{path}::{name}")
    assert missing == []
    assert len(REFERENCE.findall(MAP)) > 30  # the pattern still matches what the map writes


def test_a_shortened_name_after_a_file_resolves_in_that_file() -> None:
    """`path::a` and `::b` in one cell: b is looked up in the same file as a."""
    missing = []
    for row in MAP.splitlines():
        current: Path | None = None
        for token in re.findall(r"`[^`]+`", row):
            body = token.strip("`")
            if "::" in body and not body.startswith("::"):
                current = ROOT / body.split("::")[0]
            elif body.startswith("::") and current is not None:
                if body[2:] not in current.read_text(encoding="utf-8"):
                    missing.append(f"{current.name}{body}")
    assert missing == []
