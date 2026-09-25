from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import TokenPair, current_user
from app.models.company import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _response(tokens: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=get_settings().jwt_access_ttl_minutes * 60,
    )


@router.post("/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    return _response(await auth.login(session, body.email, body.password))


@router.post("/refresh")
async def refresh(
    body: RefreshRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    return _response(await auth.refresh(session, body.refresh_token))


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await auth.change_password(session, user, body.current_password, body.new_password)
    return Response(status_code=204)
