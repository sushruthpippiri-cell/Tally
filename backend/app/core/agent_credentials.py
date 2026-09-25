"""Agent credentials and registration tokens (D-011, SEC-2.0a/b, SEC-2.4).

Credential = `agt_<agent_id>.<secret>`; the backend stores only SHA-256(salt || secret) and a
per-Agent random salt, and verifies with a constant-time compare. Bearer over TLS only: no
request signing (SEC-2.4).
"""

import hashlib
import hmac
import secrets
import uuid

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
