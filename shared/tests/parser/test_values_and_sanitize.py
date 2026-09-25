"""P4.4: scalar values and response sanitising (GATE-G27, GATE-G35)."""

from datetime import date
from decimal import Decimal

import pytest

from tally_contract.parser.sanitize import decode, strip_invalid
from tally_contract.values import (
    parse_bool,
    parse_date,
    parse_decimal,
    parse_int,
    parse_quantity,
    parse_rate,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1180.00", (Decimal("1180.00"), None)),
        (" -1,180.50 ", (Decimal("-1180.50"), None)),
        ("1,180.00 Dr", (Decimal("1180.00"), "Dr")),
        ("500 cr", (Decimal("500"), "Cr")),
        ("0", (Decimal("0"), None)),
        (".5", (Decimal("0.5"), None)),
    ],
)
def test_numbers_are_parsed_tolerantly(raw: str, expected: tuple[Decimal, str | None]) -> None:
    assert parse_decimal(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3", "12 Nos", "1e5", None])
def test_anything_else_fails_the_record(raw: str | None) -> None:
    with pytest.raises(ValueError):
        parse_decimal(raw)


def test_dates_ints_and_logicals() -> None:
    assert parse_date("20240401") == date(2024, 4, 1)
    assert parse_int(" 1,204 ") == 1204
    assert (parse_bool("Yes"), parse_bool("no"), parse_bool("")) == (True, False, None)
    for bad in ("2024-04-01", "1-Apr-2024", "20240231"):
        with pytest.raises(ValueError):
            parse_date(bad)
    with pytest.raises(ValueError):
        parse_bool("Y")
    with pytest.raises(ValueError):
        parse_int("12.5")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12 Nos", (Decimal("12"), "Nos")),
        (" 1,200.5 Kgs", (Decimal("1200.5"), "Kgs")),
        ("2 Box = 24 Nos", (Decimal("2"), "Box")),
        ("-3 Nos", (Decimal("-3"), "Nos")),
        ("7", (Decimal("7"), None)),
        ("", (None, None)),
    ],
)
def test_quantities_carry_their_unit(raw: str, expected: tuple[object, object]) -> None:
    assert parse_quantity(raw) == expected


def test_rates_carry_their_unit() -> None:
    assert parse_rate("100.00/Nos") == (Decimal("100.00"), "Nos")
    assert parse_rate("") == (None, None)


def test_invalid_xml_characters_and_references_are_removed_and_counted() -> None:
    text, removed = strip_invalid("<P>&#4; Primary\x04</P><A>&amp; &#233; &#x9;</A>")
    assert text == "<P> Primary</P><A>&amp; &#233; &#x9;</A>"
    assert removed == 2


def test_utf8_utf16_and_bom_are_decoded() -> None:
    xml = "<A>Sharma & Sons ₹</A>"
    assert decode(xml.encode("utf-8")) == xml
    assert decode(b"\xef\xbb\xbf" + xml.encode("utf-8")) == xml
    assert decode(xml.encode("utf-16")) == xml  # with BOM
    assert decode(xml.encode("utf-16-le")) == xml  # without BOM
    with pytest.raises(UnicodeDecodeError):
        decode(b"<A>\xff\xfe\xfa</A>"[:4] + b"\xc3\x28")
