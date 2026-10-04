"""The bundled fonts are the PDF's only font source (D-053 #7b), so they must be present and
unchanged: a font file is binary, and its hash is the only review there is."""

import hashlib
import re
from pathlib import Path

import pytest

FONTS = Path(__file__).resolve().parents[2] / "app" / "exports" / "fonts"
README = FONTS / "README.md"
ROW = re.compile(r"^\| `([^`]+)` \| \d+ KB \| `([0-9a-f]{64})` \|$", re.MULTILINE)


def pinned() -> dict[str, str]:
    return dict(ROW.findall(README.read_text(encoding="utf-8")))


def test_every_font_in_the_repo_is_pinned_and_every_pin_has_its_font() -> None:
    assert set(pinned()) == {f.name for f in FONTS.glob("*.ttf")}


@pytest.mark.parametrize("name", sorted(pinned()))
def test_a_font_matches_its_pinned_hash(name: str) -> None:
    digest = hashlib.sha256((FONTS / name).read_bytes()).hexdigest()
    assert digest == pinned()[name], f"{name} changed; update its row in fonts/README.md"


def test_the_indic_scripts_of_the_rupee_are_all_covered() -> None:
    # Tally names come in these scripts; without the face the PDF would show empty boxes.
    scripts = "Devanagari Bengali Gurmukhi Gujarati Oriya Tamil Telugu Kannada Malayalam".split()
    assert all((FONTS / f"NotoSans{s}-Regular.ttf").exists() for s in scripts)
    assert (FONTS / "DejaVuSans.ttf").exists() and (FONTS / "DejaVuSans-Bold.ttf").exists()


def test_both_licences_ship_beside_the_fonts() -> None:
    ofl = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in ofl
    # The OFL needs each upstream's own copyright notice, not just one of them.
    assert ofl.count("The Noto Project Authors") == 9
    assert "Bitstream Vera" in (FONTS / "LICENSE-DejaVu.txt").read_text(encoding="utf-8")
