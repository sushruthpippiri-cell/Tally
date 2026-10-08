"""AppError and the JSON error shape: {"code", "message", "details"} (SRS 19.2)."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)

# Framework-raised HTTP errors that map onto our codes; anything else keeps FastAPI's default.
_STATUS_CODES = {
    401: ErrorCode.NOT_AUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details


def _body(code: ErrorCode, message: str, details: Any = None) -> dict[str, Any]:
    return {"code": code.value, "message": message, "details": details}


def error_response(
    code: ErrorCode, message: str, status: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    """The standard error body, for code that runs outside a route (middleware)."""
    return JSONResponse(_body(code, message), status_code=status, headers=headers)


def driver_fields(exc: BaseException) -> dict[str, str]:
    """The database driver's **primary message and SQLSTATE only**, for logging.

    PostgreSQL returns the offending row in a DETAIL line - `Failing row contains (127, …,
    Sharma Traders invoice 4,50,000, …)` - which is every column's value: a party name, an
    amount, a narration. `str()` on the error includes it, so the fields are read one by one
    off the exception chain and `detail` is never one of them. asyncpg keeps the primary
    message on the chained `PostgresError`, which the DBAPI wrapper does not expose directly.

    Residual, worth knowing rather than hiding: a *primary* message can itself quote a literal
    (`invalid input syntax for type integer: "abc"`). Constraint violations - the common case -
    name the constraint and no values. There is no narrower field than this one.
    """
    fields: dict[str, str] = {}
    original = getattr(exc, "orig", None)
    for err in (exc, original, getattr(original, "__cause__", None)):
        if err is None:
            continue
        state = getattr(err, "sqlstate", None)
        if state and "sqlstate" not in fields:
            fields["sqlstate"] = str(state)
        message = getattr(err, "message", None)
        if message and "driver_message" not in fields:
            fields["driver_message"] = str(message)[:200]
    if "driver_message" not in fields:
        # Not a PostgresError (a connection-level failure carries no structured fields): the
        # first line only, so a DETAIL block on a later line can never be included.
        fields["driver_message"] = str(original if original is not None else exc).split("\n", 1)[0][
            :200
        ]
    return fields


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        log.info("app_error", code=exc.code.value, status=exc.http_status, message=exc.message)
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": jsonable_encoder(exc.errors())}
        return JSONResponse(
            _body(ErrorCode.VALIDATION_ERROR, "Request validation failed", details),
            status_code=422,
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _database_unavailable(_: Request, exc: Exception) -> JSONResponse:
        """SRS 16: the database being unreachable is 503, not 500.

        Only the driver errors that mean "cannot talk to the database" - an IntegrityError is a
        bug in our SQL and must keep its 500. Nothing is committed on the way out: a request's
        session commits only where the code says so, so a failure part way through leaves the
        transaction to roll back.

        An `InterfaceError` that left the connection usable is **not** an outage: asyncpg raises
        it both for a lost connection and for a statement with too many bind parameters, which is
        a bug in our SQL. P16.5's benchmark hit the second and this handler called it 503, so the
        Agent treated a permanent defect as transient and retried it with backoff until its lease
        lapsed. SQLAlchemy's own `connection_invalidated` tells the two apart, so a programming
        error gets its 500 and is loud.
        """
        if isinstance(exc, InterfaceError) and not exc.connection_invalidated:
            raise exc
        # `driver_fields` and nothing else: never str(exc) or str(exc.orig), which carry the
        # statement, its parameters and PostgreSQL's DETAIL line with the whole failing row.
        log.error("database_unavailable", error=type(exc).__name__, **driver_fields(exc))
        return JSONResponse(
            _body(ErrorCode.DATABASE_UNAVAILABLE, "The service is temporarily unavailable"),
            status_code=503,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        code = _STATUS_CODES.get(exc.status_code)
        if code is None:
            return await http_exception_handler(request, exc)
        return JSONResponse(
            _body(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers
        )
