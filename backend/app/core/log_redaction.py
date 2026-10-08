"""Keep database exception text out of whatever logs a traceback (P16.5).

`driver_fields` keeps PostgreSQL's DETAIL out of the records *we* write. This is the other
path, and it is the one that actually leaked: Starlette's `ServerErrorMiddleware` re-raises an
unhandled exception after the 500 response, precisely so the server can log the traceback, and
a traceback ends with `str(exc)`. For a database error that is:

    …violates check constraint "ck_ai_tool_log_status"
    DETAIL:  Failing row contains (127, …, Sharma Traders invoice 4,50,000, …)
    [SQL: INSERT INTO ai_tool_log …]
    [parameters: {'planted': 'Sharma Traders invoice 4,50,000'}]

- PostgreSQL's DETAIL is the whole failing row: every column value.
- SQLAlchemy's `StatementError` adds the statement and its bound parameters.

Both are customer data, and logs are routinely shipped somewhere less guarded than the
database. A deploy-time grep would only find it after the fact, so the exception text is
replaced before any formatter sees it - the stack frames are kept, because frames are our own
code and are what makes a traceback worth having.
"""

import logging

from sqlalchemy.exc import DBAPIError, StatementError

from app.core.errors import driver_fields

REDACTED = "database error text redacted (P16.5): "


class RedactedDatabaseError(Exception):
    """Stands in for a database exception when a traceback is formatted."""


def _database_error(exc: BaseException) -> BaseException | None:
    """The first database exception in the chain, following both `raise … from` and context."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, DBAPIError | StatementError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _surrogate(exc: BaseException, found: BaseException) -> RedactedDatabaseError:
    fields = driver_fields(found)
    safe = RedactedDatabaseError(
        REDACTED
        + " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
        + f" [{type(found).__name__}]"
    )
    # The original frames, which are our own code; no cause and no context, or the formatter
    # would walk back to the driver's exception and print its text after all.
    safe.__traceback__ = exc.__traceback__
    safe.__suppress_context__ = True
    return safe


class RedactDatabaseErrors(logging.Filter):
    """Replaces a database exception with a safe surrogate before anything formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        info = record.exc_info
        if info and info[1] is not None:
            found = _database_error(info[1])
            if found is not None:
                safe = _surrogate(info[1], found)
                record.exc_info = (type(safe), safe, safe.__traceback__)
        return True


# uvicorn logs an unhandled ASGI exception here, with its own handler and propagate=False, so a
# filter on the root logger alone would never see it.
SERVER_LOGGERS = ("uvicorn.error", "gunicorn.error", "hypercorn.error")


def install(*, root: logging.Logger | None = None) -> RedactDatabaseErrors:
    """Attach the filter wherever a traceback can be formatted.

    Both to the loggers a server writes to and to the root logger's handlers: a filter on a
    logger runs only for records logged directly to it, so a record propagating up from a child
    would otherwise slip past.
    """
    redactor = RedactDatabaseErrors()
    for name in SERVER_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactDatabaseErrors) for f in logger.filters):
            logger.addFilter(redactor)
    for handler in (root or logging.getLogger()).handlers:
        if not any(isinstance(f, RedactDatabaseErrors) for f in handler.filters):
            handler.addFilter(redactor)
    return redactor
