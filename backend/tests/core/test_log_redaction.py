"""P16.5: the filter that keeps database exception text out of a formatted traceback.

The end-to-end proof is backend/tests/e2e/test_log_redaction.py, through a real uvicorn. These
pin the behaviour directly: what is dropped, what is kept, and that the stack survives - a
traceback with no frames would be safe and useless.
"""

import logging

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.log_redaction import REDACTED, RedactDatabaseErrors, install

PLANTED = "Sharma Traders invoice 4,50,000"


def _record(exc: BaseException) -> logging.LogRecord:
    record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, "boom", None, None)
    record.exc_info = (type(exc), exc, exc.__traceback__)
    return record


def _raised(exc: BaseException) -> BaseException:
    """The exception with a real traceback attached, as a server would see it."""
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001 - the point is to capture any traceback
        return caught


def _formatted(record: logging.LogRecord) -> str:
    return logging.Formatter().format(record)


def _database_error() -> IntegrityError:
    """What SQLAlchemy raises for a check violation: DETAIL plus the statement and parameters."""
    driver = Exception(
        'new row for relation "ai_tool_log" violates check constraint "ck_ai_tool_log_status"\n'
        f"DETAIL:  Failing row contains (127, abc, {PLANTED}, NOT_A_STATUS)."
    )
    return IntegrityError(
        "INSERT INTO ai_tool_log (result_summary) VALUES (%(planted)s)",
        {"planted": PLANTED},
        driver,
    )


@pytest.mark.req("SEC-1.13")
def test_the_row_the_statement_and_the_parameters_are_all_dropped() -> None:
    # Unfiltered, the record really does carry the row: that is what is being prevented.
    unfiltered = _formatted(_record(_raised(_database_error())))
    assert PLANTED in unfiltered and "Failing row contains" in unfiltered

    record = _record(_raised(_database_error()))
    assert RedactDatabaseErrors().filter(record) is True
    text = _formatted(record)

    for forbidden in (PLANTED, "Failing row contains", "DETAIL:", "INSERT INTO ai_tool_log"):
        assert forbidden not in text, forbidden


@pytest.mark.req("SEC-1.13")
def test_what_is_kept_is_enough_to_act_on() -> None:
    """Redaction that leaves nothing diagnosable would just be deleted by the next person."""
    record = _record(_raised(_database_error()))
    RedactDatabaseErrors().filter(record)
    text = _formatted(record)

    assert REDACTED in text
    assert "IntegrityError" in text, "the kind of failure must survive"
    assert "ck_ai_tool_log_status" in text, "the constraint is the primary message, not a value"
    # And the frames: the file this exception was raised in.
    assert "test_log_redaction.py" in text and "Traceback" in text


def test_the_chain_is_followed_through_cause_and_context() -> None:
    """SQLAlchemy raises `from` the driver error, and a handler can add another layer. The
    database error is found wherever it sits, or the dangerous text slips past."""
    inner = _raised(_database_error())
    try:
        try:
            raise inner
        except BaseException as cause:
            raise RuntimeError("while ingesting a batch") from cause
    except BaseException as outer:
        wrapped = outer

    record = _record(wrapped)
    RedactDatabaseErrors().filter(record)
    text = _formatted(record)
    assert PLANTED not in text and "DETAIL:" not in text


def test_an_exception_that_is_not_a_database_error_is_untouched() -> None:
    """The filter must not swallow everything else: a plain bug keeps its own message."""
    record = _record(_raised(ValueError("a perfectly ordinary bug")))
    RedactDatabaseErrors().filter(record)
    text = _formatted(record)
    assert "a perfectly ordinary bug" in text


def test_a_record_with_no_exception_passes_through() -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET /", None, None)
    assert RedactDatabaseErrors().filter(record) is True
    assert "GET /" in _formatted(record)


def test_install_covers_the_server_loggers_and_the_root_handlers() -> None:
    """uvicorn logs an unhandled ASGI exception to `uvicorn.error` with its own handler and
    propagate=False, so a filter on the root logger alone would never see it."""
    root = logging.Logger("isolated-root")
    root.addHandler(logging.NullHandler())
    install(root=root)

    assert any(
        isinstance(f, RedactDatabaseErrors) for f in logging.getLogger("uvicorn.error").filters
    )
    assert any(isinstance(f, RedactDatabaseErrors) for f in root.handlers[0].filters)


def test_install_is_idempotent() -> None:
    """create_app() runs per process, and a test suite makes many; the filters must not pile up."""
    root = logging.Logger("isolated-root-2")
    root.addHandler(logging.NullHandler())
    install(root=root)
    install(root=root)
    assert sum(isinstance(f, RedactDatabaseErrors) for f in root.handlers[0].filters) == 1


def test_an_operational_error_keeps_its_sqlstate_shape() -> None:
    """A genuine outage is a database error too, and must stay diagnosable after redaction."""
    exc = _raised(OperationalError("SELECT 1", {}, Exception("connection refused")))
    record = _record(exc)
    RedactDatabaseErrors().filter(record)
    text = _formatted(record)
    assert REDACTED in text and "OperationalError" in text
