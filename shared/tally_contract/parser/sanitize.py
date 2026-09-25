"""Turning Tally's response bytes into text an XML parser accepts (GATE-G35).

Tally is known to emit characters that XML 1.0 forbids, both raw and as character references
(e.g. `&#4;` before "Primary"). They are removed and counted; the encoding is taken from a BOM,
else UTF-16 is recognised by its NUL bytes, else UTF-8 (strict: bad bytes are a document error,
never silently replaced).
"""

import re

_INVALID_RAW = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_CHAR_REF = re.compile(r"&#(x[0-9a-fA-F]+|[0-9]+);")


def _allowed(codepoint: int) -> bool:
    return (
        codepoint in (0x9, 0xA, 0xD)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode("utf-16-le")
    return raw.decode("utf-8")


def strip_invalid(text: str) -> tuple[str, int]:
    """(clean text, number of invalid characters and references removed)."""
    removed = 0

    def _ref(match: re.Match[str]) -> str:
        nonlocal removed
        body = match.group(1)
        codepoint = int(body[1:], 16) if body[0] in "xX" else int(body)
        if _allowed(codepoint):
            return match.group(0)
        removed += 1
        return ""

    text = _CHAR_REF.sub(_ref, text)
    text, raw_count = _INVALID_RAW.subn("", text)
    return text, removed + raw_count
