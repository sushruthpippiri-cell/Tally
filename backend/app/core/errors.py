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
        # The driver's own message (`exc.orig`), not SQLAlchemy's: SQLAlchemy's str() includes
        # the statement and sometimes its parameters, which would put business data in the logs.
        # Without this the log said only "InterfaceError", which is not enough to act on.
        log.error(
            "database_unavailable",
            error=type(exc).__name__,
            driver_message=str(getattr(exc, "orig", "") or "")[:200],
        )
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
