"""Transcribe the SRS PDF into docs/srs/SRS_v7_3.md (P0.11).

Two files are committed:

* ``SRS_v7_3.raw.txt`` - the exact ``pdftotext -layout`` output, the reference extraction.
* ``SRS_v7_3.md``      - ``to_markdown()`` of that file: section headings become Markdown
  headings and every body block is wrapped in a ``text`` fence so table columns survive.
  Nothing is summarized or reworded.

The reference extraction is committed because ``pdftotext``'s whitespace and diagram layout
differ between poppler versions (an older poppler on CI does not reproduce a newer one's output
byte for byte). Pinning it makes the faithfulness tests deterministic on every platform:
``SRS_v7_3.md`` must equal ``to_markdown(raw)`` word for word, and the raw file is tied to the
live PDF by requirement-ID coverage, which is stable across poppler versions.
``docs/srs/README.md`` records the poppler version that produced the committed extraction.

    uv run python -m tally_tools.srs
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
PDF = ROOT / "docs/srs/Tally_SRS_v7_3_Complete.pdf"
RAW = ROOT / "docs/srs/SRS_v7_3.raw.txt"
MD = ROOT / "docs/srs/SRS_v7_3.md"

# "1. Title", "1.1 Title", "1.1.1 Title", "Appendix A. Title" at column 0.
_HEADING = re.compile(r"^(?:(\d+)\.?((?:\.\d+)*)|Appendix [A-Z]\.) +\S")
_MAX_HEADING_LEN = 70  # longer lines are Q&A rows or wrapped table text, not headings


def pdf_layout_text(pdf: Path = PDF) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True, text=True
    ).stdout


def pdf_raw_text(pdf: Path = PDF) -> str:
    return subprocess.run(
        ["pdftotext", str(pdf), "-"], check=True, capture_output=True, text=True
    ).stdout


def poppler_version() -> str:
    out = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True)
    return (out.stderr or out.stdout).splitlines()[0].strip()


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
    """Pure function: reference extraction -> Markdown. Deterministic on every platform."""
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
    raw = pdf_layout_text(PDF)
    RAW.write_text(raw, encoding="utf-8", newline="\n")
    MD.write_text(to_markdown(raw), encoding="utf-8", newline="\n")
    sys.stderr.write(f"wrote {RAW.name} and {MD.name} using {poppler_version()}\n")


if __name__ == "__main__":
    main()
