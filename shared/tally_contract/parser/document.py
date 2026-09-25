"""Parsing one Tally response (P4.4). Nothing raises out of here (TEST-1.4, AC-66):
- a document that cannot be read at all, or a Tally error response, gives a DocumentError
  and no records;
- a record that cannot be built gives a ParseError and parsing continues (SYNC-6.5).
Records are streamed (iterparse) and each element is cleared once built.
"""

import io
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, ValidationError

from tally_contract import tally_constants as tc
from tally_contract.errors import ErrorCode
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


def _elements(text: str, record_tag: str) -> Iterator[ET.Element]:
    for _, element in ET.iterparse(io.StringIO(text), events=("end",)):
        if element.tag == record_tag:
            yield element
            element.clear()


def parse[R](raw: bytes, record_tag: str, build: Callable[[ET.Element], R]) -> ParseResult[R]:
    result: ParseResult[R] = ParseResult()
    try:
        text, result.invalid_characters_removed = strip_invalid(decode(raw))
        if result.invalid_characters_removed:
            log.info("tally_invalid_characters_removed", count=result.invalid_characters_removed)
        error = tally_error(text)
        if error is not None:
            return _fail(result, error)
        for element in _elements(text, record_tag):
            try:
                result.records.append(build(element))
            except (ValueError, ValidationError, KeyError, TypeError) as exc:
                guid = (element.findtext("GUID") or "").strip() or None
                snippet = ET.tostring(element, encoding="unicode")[:SNIPPET]
                result.errors.append(
                    ParseError(guid=guid, message=str(exc)[:1000], snippet=snippet)
                )
                log.warning("record_parse_failed", record_tag=record_tag, guid=guid, error=str(exc))
    except UnicodeDecodeError as exc:
        return _fail(
            result, DocumentError(code=ErrorCode.PARSE_ERROR, message=f"not UTF-8/16: {exc}")
        )
    except ET.ParseError as exc:
        return _fail(
            result, DocumentError(code=ErrorCode.PARSE_ERROR, message=f"malformed XML: {exc}")
        )
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
