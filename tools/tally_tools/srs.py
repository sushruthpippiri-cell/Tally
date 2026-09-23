"""Transcribe the SRS PDF into docs/srs/SRS_v7_3.md (P0.11).

The text is `pdftotext -layout` output, unchanged except that section headings become Markdown
headings and every body block is wrapped in a ```text fence so table columns survive. Nothing is
summarized or reworded; `tests/test_srs_transcription.py` proves the words are identical.

    uv run python -m tally_tools.srs docs/srs/Tally_SRS_v7_3_Complete.pdf docs/srs/SRS_v7_3.md
"""

import re
import subprocess
import sys
from pathlib import Path

# "1. Title", "1.1 Title", "1.1.1 Title", "Appendix A. Title" at column 0.
_HEADING = re.compile(r"^(?:(\d+)\.?((?:\.\d+)*)|Appendix [A-Z]\.) +\S")
_MAX_HEADING_LEN = 70  # longer lines are Q&A rows or wrapped table text, not headings


def pdf_layout_text(pdf: Path) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True, text=True
    ).stdout


def pdf_raw_text(pdf: Path) -> str:
    return subprocess.run(
        ["pdftotext", str(pdf), "-"], check=True, capture_output=True, text=True
    ).stdout


def heading_level(line: str) -> int | None:
    """1 for '1. X' / 'Appendix A. X', 2 for '1.1 X', ...; None when the line is not a heading."""
    if len(line) > _MAX_HEADING_LEN or line.rstrip().endswith("."):
        return None
    m = _HEADING.match(line)
    if not m:
        return None
    if line.startswith("Appendix"):
        return 1
    return 1 + m.group(2).count(".")


def to_markdown(layout: str) -> str:
    out: list[str] = []
    body: list[str] = []

    def flush() -> None:
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if body:
            out.extend(["```text", *body, "```", ""])
        body.clear()

    for raw in layout.replace("\f", "\n").splitlines():
        line = raw.rstrip()
        level = heading_level(line)
        if level is not None:
            flush()
            out.extend([f"{'#' * level} {line}", ""])
        elif line or (body and body[-1].strip()):  # collapse runs of blank lines
            body.append(line)
    flush()
    return "\n".join(out)


def main() -> None:
    pdf, dest = Path(sys.argv[1]), Path(sys.argv[2])
    dest.write_text(to_markdown(pdf_layout_text(pdf)))
    sys.stderr.write(f"wrote {dest}\n")


if __name__ == "__main__":
    main()
