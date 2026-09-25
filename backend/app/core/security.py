"""Passwords, JWTs and the current-user dependency (SEC-1.1, D-033).

Access tokens carry only the user id; roles are read from user_roles on every request, so a
role removal applies on the next request (D-033 #9).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.models.company import RefreshToken, User
from tally_contract.errors import ErrorCode

TokenType = Literal["access", "refresh"]
_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode()
    if len(raw) > 72:  # bcrypt's limit; such a password can never have been set
        return False
    return bcrypt.checkpw(raw, password_hash.encode())


@lru_cache
def _dummy_hash() -> str:
    return hash_password("timing-equaliser")


def burn_password_check(password: str) -> None:
    """Same cost as a real check, so an unknown email is not faster to reject."""
    verify_password(password, _dummy_hash())


def normalize_email(email: str) -> str:
    return email.strip().lower()


def unauthenticated(message: str = "Not authenticated") -> AppError:
    return AppError(ErrorCode.NOT_AUTHENTICATED, message, 401)


def _encode(claims: dict[str, Any]) -> str:
    secret = get_settings().jwt_secret
    assert secret is not None  # guaranteed by Settings validation
    return jwt.encode(claims, secret.get_secret_value(), algorithm=_ALGORITHM)


def decode_token(token: str, expected: TokenType) -> dict[str, Any]:
    secret = get_settings().jwt_secret
    assert secret is not None
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise unauthenticated() from exc
    if claims["type"] != expected:
        raise unauthenticated()
    return claims


def create_access_token(user_id: uuid.UUID) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=get_settings().jwt_access_ttl_minutes)
    return _encode({"sub": str(user_id), "type": "access", "exp": exp})


async def issue_refresh_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    jti = uuid.uuid4()
    exp = datetime.now(UTC) + timedelta(hours=get_settings().jwt_refresh_ttl_hours)
    session.add(RefreshToken(jti=jti, user_id=user_id, expires_at=exp))
    await session.flush()
    return _encode({"sub": str(user_id), "type": "refresh", "jti": str(jti), "exp": exp})


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


async def issue_tokens(session: AsyncSession, user_id: uuid.UUID) -> TokenPair:
    return TokenPair(create_access_token(user_id), await issue_refresh_token(session, user_id))


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """401 unless a valid access token names an active user (re-read on every request)."""
    if credentials is None:
        raise unauthenticated()
    claims = decode_token(credentials.credentials, "access")
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError as exc:
        raise unauthenticated() from exc
    user = (await session.execute(select(User).where(User.user_id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise unauthenticated()
    return user
