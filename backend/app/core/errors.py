"""AppError and the JSON error shape: {"code", "message", "details"} (SRS 19.2)."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
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

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        code = _STATUS_CODES.get(exc.status_code)
        if code is None:
            return await http_exception_handler(request, exc)
        return JSONResponse(
            _body(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers
        )
