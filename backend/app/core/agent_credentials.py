"""Agent credentials and registration tokens (D-011, SEC-2.0a/b, SEC-2.4).

Credential = `agt_<agent_id>.<secret>`; the backend stores only SHA-256(salt || secret) and a
per-Agent random salt, and verifies with a constant-time compare. Bearer over TLS only: no
request signing (SEC-2.4).
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.models.agents import Agent
from app.models.enums import AgentStatus
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)

CREDENTIAL_PREFIX = "agt_"
TOKEN_PREFIX = "reg_"


def _hash(salt: bytes, secret: str) -> str:
    return hashlib.sha256(salt + secret.encode()).hexdigest()


def new_credential(agent_id: uuid.UUID) -> tuple[str, bytes, str]:
    """(credential shown once, salt to store, hash to store)."""
    secret = secrets.token_urlsafe(48)
    salt = secrets.token_bytes(16)
    return f"{CREDENTIAL_PREFIX}{agent_id}.{secret}", salt, _hash(salt, secret)


def parse(credential: str) -> tuple[uuid.UUID, str] | None:
    """(agent_id, secret), or None if it is not an Agent credential."""
    if not credential.startswith(CREDENTIAL_PREFIX):
        return None
    agent_part, dot, secret = credential[len(CREDENTIAL_PREFIX) :].partition(".")
    if not dot or not secret:
        return None
    try:
        return uuid.UUID(agent_part), secret
    except ValueError:
        return None


def verify(secret: str, salt: bytes, stored_hash: str) -> bool:
    return hmac.compare_digest(_hash(salt, secret), stored_hash)


def new_registration_token() -> tuple[str, str]:
    """(token shown once, hash to store). Single use, 24 h (SRS 4.2 step 3)."""
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return token, hash_registration_token(token)


def hash_registration_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AgentContext:
    """The calling Agent. Its company_id is the only company Agent requests may touch."""

    agent_id: uuid.UUID
    company_id: uuid.UUID
    status: AgentStatus


def _invalid() -> AppError:
    return AppError(ErrorCode.CREDENTIAL_INVALID, "Invalid Agent credential", 401)


async def current_agent(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> AgentContext:
    """401 CREDENTIAL_INVALID unless the bearer is a valid Agent credential; 401 AGENT_REVOKED
    for a revoked Agent presenting its correct secret (SEC-2.2). A wrong secret never reveals
    whether the Agent exists or is revoked."""
    parsed = parse(credentials.credentials) if credentials else None
    if parsed is None:
        raise _invalid()
    agent_id, secret = parsed
    agent = await session.get(Agent, agent_id)
    if (
        agent is None
        or agent.credential_salt is None
        or agent.credential_hash is None
        or not verify(secret, agent.credential_salt, agent.credential_hash)
    ):
        log.info("agent_credential_invalid", agent_id=str(agent_id))
        raise _invalid()
    if agent.status == AgentStatus.REVOKED:
        log.info("agent_revoked_rejected", agent_id=str(agent_id))
        raise AppError(
            ErrorCode.AGENT_REVOKED, "This Agent has been revoked; register it again", 401
        )
    return AgentContext(agent.agent_id, agent.company_id, AgentStatus(agent.status))
