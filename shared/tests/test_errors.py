import re
from pathlib import Path

from tally_contract.errors import PROPOSED_CODES, SRS_CODES, ErrorCode
from tally_contract.version import CONTRACT_VERSION

ROOT = Path(__file__).parents[2]


def test_counts_and_disjoint() -> None:
    assert len(SRS_CODES) == 15
    assert len(PROPOSED_CODES) == 14
    assert not set(SRS_CODES) & set(PROPOSED_CODES)
    assert set(ErrorCode) == set(SRS_CODES) | set(PROPOSED_CODES)


def test_values_equal_names() -> None:
    assert all(c.value == c.name for c in ErrorCode)


def test_every_proposed_code_is_marked_in_source() -> None:
    src = (ROOT / "shared/tally_contract/errors.py").read_text()
    for code in PROPOSED_CODES:
        assert re.search(rf"^\s*{code.name} = .*# not in SRS v7\.3", src, re.M), code.name


def test_proposed_codes_match_decision_d030() -> None:
    text = (ROOT / "docs/decisions.md").read_text()
    section = text[text.index("### D-030") :]
    listed = set(re.findall(r"^\| `([A-Z_]+)` \|", section, re.M))
    assert listed == {c.name for c in PROPOSED_CODES}


def test_all_srs_codes_exist_in_srs_pdf_text() -> None:
    srs = ROOT / "docs/srs/SRS_v7_3.md"
    if not srs.exists():
        import pytest

        pytest.skip("waiting on P0.11 (docs/srs/SRS_v7_3.md not created yet)")
    text = srs.read_text()
    assert all(c.name in text for c in SRS_CODES)
    assert not any(re.search(rf"\b{c.name}\b", text) for c in PROPOSED_CODES)


def test_contract_version() -> None:
    assert CONTRACT_VERSION == "1.0"
