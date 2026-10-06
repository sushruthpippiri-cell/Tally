"""Parsing one Tally response (P4.4). Nothing raises out of here (TEST-1.4, AC-66):
- a document that cannot be read at all, or a Tally error response, gives a DocumentError
  and no records;
- a record that cannot be built gives a ParseError and parsing continues (SYNC-6.5).
Records are streamed (iterparse) and each element is cleared once built.
"""

import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import cast

from pydantic import BaseModel, ConfigDict, ValidationError

from tally_contract import tally_constants as tc
from tally_contract.errors import ErrorCode, RecordRejected
from tally_contract.log import get_logger
from tally_contract.parser.sanitize import decode, strip_invalid
from tally_contract.records import ParseError

log = get_logger(__name__)
SNIPPET = 500


class DocumentError(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: ErrorCode
    message: str


@dataclass
class ParseResult[R]:
    records: list[R] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    document_error: DocumentError | None = None
    invalid_characters_removed: int = 0

    @property
    def ok(self) -> bool:
        return self.document_error is None


def tally_error(text: str) -> DocumentError | None:
    """GATE-G35: Tally answers an unknown report or unopened company with an error message."""
    if tc.ERROR_TAG not in text and not any(
        m in text for m in (*tc.REPORT_NOT_FOUND_MARKERS, *tc.COMPANY_NOT_LOADED_MARKERS)
    ):
        return None
    if any(m in text for m in tc.REPORT_NOT_FOUND_MARKERS):
        return DocumentError(
            code=ErrorCode.TDL_NOT_LOADED,
            message="The project TDL is not loaded in TallyPrime (FR-1.4)",
        )
    if any(m in text for m in tc.COMPANY_NOT_LOADED_MARKERS):
        return DocumentError(
            code=ErrorCode.COMPANY_NOT_LOADED,
            message="The named company is not open in TallyPrime (AGT-5.3)",
        )
    start = text.find(tc.ERROR_TAG)
    return DocumentError(
        code=ErrorCode.PARSE_ERROR, message=f"Tally returned an error: {text[start : start + 300]}"
    )


def doctype_error(text: str) -> DocumentError | None:
    """SEC-1.6 (P16.2): refuse a document declaring a DTD.

    xml.etree does not resolve external entities - a `SYSTEM` entity raises "undefined entity",
    so there is no file disclosure - but it *does* expand internal ones, so a "billion laughs"
    document would expand exponentially and exhaust the Agent before any record was built.
    TallyPrime's reports never carry a DOCTYPE, so refusing one costs nothing and removes the
    whole class.
    """
    if "<!DOCTYPE" not in text.upper():
        return None
    return DocumentError(
        code=ErrorCode.PARSE_ERROR,
        message="XML declaring a DTD is refused; Tally reports carry none (SEC-1.6)",
    )


FEED = 65_536  # characters per slice: no second full copy of the document (D-042 #2)


def _elements(text: str, record_tag: str) -> Iterator[ET.Element]:
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("end",))

    def ready() -> Iterator[ET.Element]:
        events = cast(Iterator[tuple[str, object]], parser.read_events())  # ("end", element)
        for _event, element in events:
            if isinstance(element, ET.Element) and element.tag == record_tag:
                yield element
                element.clear()

    for start in range(0, len(text), FEED):
        parser.feed(text[start : start + FEED])
        yield from ready()
    parser.close()
    yield from ready()


class DocumentFailure(Exception):
    """Raised by `iter_parse` when the document as a whole cannot be trusted."""

    def __init__(self, error: DocumentError) -> None:
        super().__init__(error.message)
        self.error = error


def iter_parse[R](
    raw: bytes,
    record_tag: str,
    build: Callable[[ET.Element], R],
    result: "ParseResult[R] | None" = None,
) -> Iterator[R | ParseError]:
    """Records (or per-record ParseErrors) one at a time, as the XML is read, so a caller can
    hand them on without holding them all (D-042 #2). A document that cannot be trusted raises
    DocumentFailure, possibly after some records were yielded: the caller must then discard
    what it took from this document (P4: never half a response)."""
    try:
        text, removed = strip_invalid(decode(raw))
    except UnicodeDecodeError as exc:
        raise DocumentFailure(
            DocumentError(code=ErrorCode.PARSE_ERROR, message=f"not UTF-8/16: {exc}")
        ) from exc
    if result is not None:
        result.invalid_characters_removed = removed
    if removed:
        log.info("tally_invalid_characters_removed", count=removed)
    error = tally_error(text) or doctype_error(text)
    if error is not None:
        raise DocumentFailure(error)
    try:
        for element in _elements(text, record_tag):
            try:
                yield build(element)
            except (ValueError, ValidationError, KeyError, TypeError) as exc:
                guid = (element.findtext("GUID") or "").strip() or None
                snippet = ET.tostring(element, encoding="unicode")[:SNIPPET]
                code = exc.code if isinstance(exc, RecordRejected) else ErrorCode.PARSE_ERROR
                log.warning("record_parse_failed", record_tag=record_tag, guid=guid, error=str(exc))
                yield ParseError(guid=guid, code=code, message=str(exc)[:1000], snippet=snippet)
    except ET.ParseError as exc:
        raise DocumentFailure(
            DocumentError(code=ErrorCode.PARSE_ERROR, message=f"malformed XML: {exc}")
        ) from exc


def parse[R](raw: bytes, record_tag: str, build: Callable[[ET.Element], R]) -> ParseResult[R]:
    """The whole document at once, for small responses and tests; never raises (TEST-1.4)."""
    result: ParseResult[R] = ParseResult()
    try:
        for item in iter_parse(raw, record_tag, build, result):
            if isinstance(item, ParseError):
                result.errors.append(item)
            else:
                result.records.append(item)
    except DocumentFailure as exc:
        return _fail(result, exc.error)
    except Exception as exc:  # the parser never raises (TEST-1.4)
        return _fail(
            result,
            DocumentError(code=ErrorCode.PARSE_ERROR, message=f"{type(exc).__name__}: {exc}"),
        )
    return result


def _fail[R](result: ParseResult[R], error: DocumentError) -> ParseResult[R]:
    """A document that cannot be trusted yields no records at all: never half a response."""
    log.error("tally_document_error", code=error.code.value, message=error.message)
    return ParseResult(
        document_error=error, invalid_characters_removed=result.invalid_characters_removed
    )
