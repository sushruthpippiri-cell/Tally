"""P0.11: SRS_v7_3.md is a faithful copy of the PDF (nothing summarized or reworded)."""

import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

from tally_tools.srs import heading_level, pdf_layout_text, pdf_raw_text, to_markdown

ROOT = Path(__file__).parents[2]
PDF = ROOT / "docs/srs/Tally_SRS_v7_3_Complete.pdf"
MD = ROOT / "docs/srs/SRS_v7_3.md"
ID = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d+(?:\.\d+)*\b")

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="needs poppler (brew install poppler)"
)


def _md_words(md: str) -> list[str]:
    lines = [ln for ln in md.splitlines() if ln != "```text" and ln != "```"]
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
        (
            "27. What happens to a cancelled or deleted voucher? It is kept with status CANCELLED",
            None,
        ),
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


@needs_poppler
@pytest.mark.req("TEST-1.3")
def test_transcription_is_word_for_word_the_pdf_text() -> None:
    assert _md_words(MD.read_text()) == pdf_layout_text(PDF).split()


@needs_poppler
def test_committed_file_is_current_output_of_the_generator() -> None:
    assert MD.read_text() == to_markdown(pdf_layout_text(PDF))


@needs_poppler
def test_every_requirement_id_in_the_pdf_is_present_with_same_count() -> None:
    md_ids = Counter(ID.findall(MD.read_text()))
    assert md_ids == Counter(ID.findall(pdf_layout_text(PDF)))
    # Independent extraction (non-layout mode) must not contain an ID the copy lacks.
    # Raw mode drops the hyphen where an ID was line-wrapped (ACC-DATA-3 -> ACCDATA-3),
    # so compare with hyphens removed.
    flat = {i.replace("-", "") for i in md_ids}
    assert {i.replace("-", "") for i in ID.findall(pdf_raw_text(PDF))} <= flat


def test_edition_and_sections() -> None:
    text = MD.read_text()
    assert "SRS v7.3" in text and "Complete Edition" in text
    heads = re.findall(r"^# (\d+)\. ", text, re.M)
    assert [int(h) for h in heads] == list(range(1, 29))
    assert "# Appendix A. Version History" in text
    assert "SYNC-3.2" in text
