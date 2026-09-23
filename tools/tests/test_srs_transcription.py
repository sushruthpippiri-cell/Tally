"""P0.11: SRS_v7_3.md is a faithful copy of the PDF (nothing summarized or reworded).

`SRS_v7_3.raw.txt` is the committed reference extraction. The markdown must be exactly what the
generator produces from it (deterministic on every platform), and the reference extraction is
tied to the live PDF by requirement-ID coverage, which is stable across poppler versions.
"""

import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

from tally_tools.srs import MD, PDF, RAW, heading_level, pdf_layout_text, pdf_raw_text, to_markdown

ID = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d+(?:\.\d+)*\b")

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftotext") is None,
    reason="needs poppler (brew install poppler / apt-get install poppler-utils)",
)


def _md_words(md: str) -> list[str]:
    lines = [ln for ln in md.splitlines() if ln not in ("```text", "```")]
    return re.sub(r"^#+ ", "", "\n".join(lines), flags=re.M).split()


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("1. Introduction", 1),
        ("6.9 Voucher child-row updates", 2),
        ("1.2.3 Deep", 3),
        ("Appendix A. Version History", 1),
        ("12.4 Why Claude, and does the system need it?", 2),
        ("17.1 targets are met and every PERF-VAL-1 field is recorded.", None),
        ("27. What happens to a cancelled voucher? It is kept with status CANCELLED", None),
        ("  1. Extracts accounting data", None),
        ("ACC-7.1 something", None),
    ],
)
def test_heading_level(line: str, level: int | None) -> None:
    assert heading_level(line) == level


def test_to_markdown_fences_body_and_keeps_words() -> None:
    src = "1. Intro\n\ntext  a   b\n\f\n1.1 Sub\nrow   x\n"
    md = to_markdown(src)
    assert "# 1. Intro" in md and "## 1.1 Sub" in md and "text  a   b" in md
    assert _md_words(md) == src.replace("#", "").split()


def test_markdown_is_exactly_the_generator_output_of_the_reference_extraction() -> None:
    assert MD.read_text(encoding="utf-8") == to_markdown(RAW.read_text(encoding="utf-8"))


def test_markdown_is_word_for_word_the_reference_extraction() -> None:
    assert _md_words(MD.read_text(encoding="utf-8")) == RAW.read_text(encoding="utf-8").split()


@needs_poppler
@pytest.mark.req("TEST-1.3")
def test_reference_extraction_carries_every_requirement_id_of_the_live_pdf() -> None:
    """Ties the committed files to the PDF itself. ID counts do not vary by poppler version."""
    pdf_ids = Counter(ID.findall(pdf_layout_text(PDF)))
    assert Counter(ID.findall(RAW.read_text(encoding="utf-8"))) == pdf_ids
    assert Counter(ID.findall(MD.read_text(encoding="utf-8"))) == pdf_ids
    # Independent extraction (non-layout mode) must not contain an ID the copy lacks.
    # Raw mode drops the hyphen where an ID was line-wrapped (ACC-DATA-3 -> ACCDATA-3),
    # so compare with hyphens removed.
    flat = {i.replace("-", "") for i in pdf_ids}
    assert {i.replace("-", "") for i in ID.findall(pdf_raw_text(PDF))} <= flat


def test_edition_and_sections() -> None:
    text = MD.read_text(encoding="utf-8")
    assert "SRS v7.3" in text and "Complete Edition" in text
    heads = re.findall(r"^# (\d+)\. ", text, re.M)
    assert [int(h) for h in heads] == list(range(1, 29))
    assert "# Appendix A. Version History" in text
    assert "SYNC-3.2" in text


def test_reference_extraction_has_unix_line_endings() -> None:
    """Committed as LF so the generator output matches on Windows too."""
    for path in (RAW, MD):
        assert b"\r\n" not in path.read_bytes(), path.name


def test_srs_readme_records_the_poppler_version() -> None:
    readme = (Path(RAW).parent / "README.md").read_text(encoding="utf-8")
    assert "poppler" in readme.lower() and "26.09.0" in readme
