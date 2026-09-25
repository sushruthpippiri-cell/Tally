"""Login, refresh rotation and password change (SEC-1.1, LOG-1.1, D-033)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import AppError
from app.core.security import (
    TokenPair,
    burn_password_check,
    decode_token,
    hash_password,
    issue_tokens,
    normalize_email,
    unauthenticated,
    verify_password,
)
from app.models.company import RefreshToken, User
from app.models.config import AuditLog
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)

LOGIN_FAILURE_LIMIT = 10
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
INVALID_LOGIN = "Invalid email or password"


async def _recent_failures(session: AsyncSession, email: str) -> int:
    cutoff = datetime.now(UTC) - LOGIN_FAILURE_WINDOW
    return (
        await session.execute(
            select(func.count()).where(
                AuditLog.action == "LOGIN",
                AuditLog.entity_id == email,
                AuditLog.result == "FAILURE",
                AuditLog.created_at > cutoff,
            )
        )
    ).scalar_one()


async def _audit_login(
    session: AsyncSession, email: str, user_id: uuid.UUID | None, result: str
) -> None:
    await audit.record(
        session,
        company_id=None,
        user_id=user_id,
        action="LOGIN",
        entity_type="user",
        entity_id=email,
        result=result,
    )
    await session.commit()


async def login(session: AsyncSession, email: str, password: str) -> TokenPair:
    key = normalize_email(email)
    # Throttled: the password is not checked, and the answer is the same for any email.
    if await _recent_failures(session, key) >= LOGIN_FAILURE_LIMIT:
        await _audit_login(session, key, None, "THROTTLED")
        log.warning("login_throttled", email=key)
        raise AppError(ErrorCode.RATE_LIMITED, "Too many login attempts; try again later", 429)
    user = (
        await session.execute(select(User).where(func.lower(User.email) == key))
    ).scalar_one_or_none()
    if user is None:
        burn_password_check(password)
    ok = user is not None and verify_password(password, user.password_hash) and user.is_active
    if not ok:
        await _audit_login(session, key, user.user_id if user else None, "FAILURE")
        raise unauthenticated(INVALID_LOGIN)
    assert user is not None
    tokens = await issue_tokens(session, user.user_id)
    await _audit_login(session, key, user.user_id, "SUCCESS")
    return tokens


async def refresh(session: AsyncSession, refresh_token: str) -> TokenPair:
    claims = decode_token(refresh_token, "refresh")
    try:
        jti = uuid.UUID(str(claims.get("jti")))
    except ValueError as exc:
        raise unauthenticated() from exc
    now = datetime.now(UTC)
    user_id = (
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.jti == jti,
                RefreshToken.used_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(RefreshToken.user_id)
        )
    ).scalar_one_or_none()
    if user_id is None:
        await _handle_possible_reuse(session, jti)
        raise unauthenticated()
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthenticated()
    tokens = await issue_tokens(session, user_id)
    await session.commit()
    return tokens


async def _handle_possible_reuse(session: AsyncSession, jti: uuid.UUID) -> None:
    """A rotated token presented again was probably stolen: close every open session."""
    token = await session.get(RefreshToken, jti)
    if token is None or token.used_at is None:
        return  # unknown, revoked or expired: a plain 401
    await revoke_refresh_tokens(session, token.user_id)
    await audit.record(
        session,
        company_id=None,
        user_id=token.user_id,
        action="REFRESH_TOKEN_REUSE",
        entity_type="user",
        entity_id=str(token.user_id),
        result="FAILURE",
    )
    await session.commit()
    log.warning("refresh_token_reuse", user_id=str(token.user_id))


async def revoke_refresh_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    # Open tokens only; rotated rows stay so a replay of them is still recognised as reuse.
    await session.execute(
        delete(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.used_at.is_(None))
    )


async def change_password(session: AsyncSession, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        await audit.record(
            session,
            company_id=None,
            user_id=user.user_id,
            action="PASSWORD_CHANGED",
            entity_type="user",
            entity_id=str(user.user_id),
            result="FAILURE",
        )
        await session.commit()
        raise AppError(ErrorCode.FORBIDDEN, "Current password is incorrect", 403)
    user.password_hash = hash_password(new)
    await revoke_refresh_tokens(session, user.user_id)
    await audit.record(
        session,
        company_id=None,
        user_id=user.user_id,
        action="PASSWORD_CHANGED",
        entity_type="user",
        entity_id=str(user.user_id),
    )
    await session.commit()
