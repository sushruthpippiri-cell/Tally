"""P3.1: Agent credentials and registration tokens (D-011)."""

import uuid

import pytest

from app.core import agent_credentials as ac


@pytest.mark.req("SEC-2.0b")
def test_only_a_salted_hash_is_stored_and_verification_hashes_and_compares() -> None:
    agent_id = uuid.uuid4()
    credential, salt, stored = ac.new_credential(agent_id)
    parsed = ac.parse(credential)
    assert parsed is not None
    got_id, secret = parsed
    assert got_id == agent_id
    assert secret not in stored and len(salt) == 16 and len(stored) == 64
    assert ac.verify(secret, salt, stored)
    assert not ac.verify(secret + "x", salt, stored)
    assert not ac.verify(secret, b"\0" * 16, stored)  # the salt is part of the hash


def test_same_secret_different_salt_gives_different_hashes() -> None:
    _, salt_a, hash_a = ac.new_credential(uuid.uuid4())
    _, salt_b, hash_b = ac.new_credential(uuid.uuid4())
    assert salt_a != salt_b and hash_a != hash_b


@pytest.mark.req_partial("SEC-2.0a")  # bearer on every request: the AgentContext tests (P3.4)
def test_credentials_are_long_and_random() -> None:
    a, _, _ = ac.new_credential(uuid.uuid4())
    b, _, _ = ac.new_credential(uuid.uuid4())
    assert a != b
    assert len(a.split(".", 1)[1]) >= 64  # 48 random bytes, url-safe


@pytest.mark.parametrize(
    "credential",
    [
        "",
        "Bearer x",
        "eyJhbGciOiJIUzI1NiJ9.e30.sig",  # a JWT
        "agt_not-a-uuid.secret",
        f"agt_{uuid.uuid4()}",
        f"agt_{uuid.uuid4()}.",
        f"reg_{uuid.uuid4()}.secret",
    ],
)
def test_malformed_credentials_do_not_parse(credential: str) -> None:
    assert ac.parse(credential) is None


def test_registration_tokens_are_hashed_and_unique() -> None:
    token, stored = ac.new_registration_token()
    assert token.startswith("reg_") and token not in stored
    assert ac.hash_registration_token(token) == stored
    assert ac.new_registration_token()[0] != token
