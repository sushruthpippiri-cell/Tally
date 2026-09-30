"""Login, refresh, logout and password change (SEC-1.1, D-033, D-051).

The refresh token lives only in an HttpOnly, Secure, SameSite=Strict cookie scoped to the auth
endpoints; script never sees it (D-051 #1). The two endpoints that read it are the only
cookie-based ones, so they alone carry CSRF checks (SEC-1.5, D-051 #2): the custom header
`X-Tally-Request: 1` and, when the browser sends one, an Origin of this site.
"""

from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import TokenPair, current_user, unauthenticated
from app.models.company import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, TokenResponse
from app.services import auth
from tally_contract.errors import ErrorCode

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "tally_refresh"
CSRF_HEADER = "x-tally-request"
REFRESH = Cookie(None, alias=REFRESH_COOKIE)


def _respond(response: Response, tokens: TokenPair) -> TokenResponse:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.jwt_refresh_ttl_hours * 3600,
        path=settings.refresh_cookie_path,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=tokens.access_token, expires_in=settings.jwt_access_ttl_minutes * 60
    )


def _check_csrf(request: Request) -> None:
    """D-051 #2: a cross-site form cannot send the header, and a cross-site fetch would need a
    CORS preflight the backend refuses; an Origin, when sent, must be this site's."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise AppError(ErrorCode.FORBIDDEN, "Missing X-Tally-Request header", 403)
    origin = request.headers.get("origin")
    if origin is not None and origin not in get_settings().cors_origins:
        if urlsplit(origin).netloc != request.headers.get("host", ""):
            raise AppError(ErrorCode.FORBIDDEN, "Request from another site refused", 403)


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    return _respond(response, await auth.login(session, body.email, body.password))


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = REFRESH,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    _check_csrf(request)
    if not refresh_token:
        raise unauthenticated()
    return _respond(response, await auth.refresh(session, refresh_token))


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    refresh_token: str | None = REFRESH,
    session: AsyncSession = Depends(get_session),
) -> Response:
    _check_csrf(request)
    await auth.logout(session, refresh_token)
    response = Response(status_code=204)
    response.delete_cookie(
        REFRESH_COOKIE,
        path=get_settings().refresh_cookie_path,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await auth.change_password(session, user, body.current_password, body.new_password)
    return Response(status_code=204)
