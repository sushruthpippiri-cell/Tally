"""P2.2: login, refresh rotation, reuse detection, login throttle, password change."""

from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import time_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.company import RefreshToken
from app.models.config import AuditLog
from tally_contract.testing import assert_logged
from tests.factories import PASSWORD, auth_header, make_company, make_user


async def _login(api: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await api.post("/auth/login", json={"email": email, "password": password})


async def _audit(session: AsyncSession, action: str) -> list[AuditLog]:
    rows = await session.execute(
        select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
    )
    return list(rows.scalars())


def _claims(token: str) -> dict[str, object]:
    return jwt.decode(token, options={"verify_signature": False})


@pytest.mark.req("SEC-1.1")
async def test_login_issues_tokens_that_expire_within_24h(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, email="Owner@Example.com")
    r = await _login(api, "  owner@example.com ")
    assert r.status_code == 200, r.text
    body = r.json()
    now = datetime.now(UTC).timestamp()
    access, refresh = _claims(body["access_token"]), _claims(body["refresh_token"])
    assert access["sub"] == refresh["sub"] == str(user.user_id)
    assert access["type"] == "access" and refresh["type"] == "refresh"
    assert float(str(access["exp"])) - now <= 30 * 60 + 5
    assert float(str(refresh["exp"])) - now <= 24 * 3600 + 5
    assert body["expires_in"] == 1800
    assert user.password_hash.startswith("$2b$")  # bcrypt
    rotated = await api.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert rotated.status_code == 200  # the refresh flow
    me = await api.post(
        "/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "x" * 10},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 403  # the access token authenticates; the password is wrong


@pytest.mark.req_partial("LOG-1.1")  # login only; each other action is audited in its phase
async def test_login_success_and_failure_are_audited(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, email="a@example.com")
    assert (await _login(api, "a@example.com")).status_code == 200
    assert (await _login(api, "a@example.com", "nope-nope")).status_code == 401
    rows = await _audit(session, "LOGIN")
    assert [(r.result, r.user_id, r.entity_id) for r in rows] == [
        ("SUCCESS", user.user_id, "a@example.com"),
        ("FAILURE", user.user_id, "a@example.com"),
    ]


async def test_wrong_password_unknown_email_and_inactive_user_look_the_same(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="a@example.com")
    await make_user(session, email="gone@example.com", is_active=False)
    answers = [
        await _login(api, "a@example.com", "wrong-password"),
        await _login(api, "nobody@example.com"),
        await _login(api, "gone@example.com"),
    ]
    assert {r.status_code for r in answers} == {401}
    assert len({r.content for r in answers}) == 1
    assert answers[0].json()["message"] == "Invalid email or password"


async def test_expired_access_token_is_rejected(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session)
    headers = auth_header(user)
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=31)):
        r = await api.post(
            "/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "new-password-1"},
            headers=headers,
        )
    assert r.status_code == 401
    assert r.json()["code"] == "NOT_AUTHENTICATED"


async def test_a_refresh_token_is_not_an_access_token(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="a@example.com")
    refresh = (await _login(api, "a@example.com")).json()["refresh_token"]
    r = await api.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-1"},
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert r.status_code == 401


async def test_refresh_rotates_the_token(api: httpx.AsyncClient, session: AsyncSession) -> None:
    await make_user(session, email="a@example.com")
    first = (await _login(api, "a@example.com")).json()
    r = await api.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    again = await api.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert again.status_code == 200


async def test_reused_refresh_token_revokes_every_open_token(
    api: httpx.AsyncClient, session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    user_id = (await make_user(session, email="a@example.com")).user_id  # read before failures
    stolen = (await _login(api, "a@example.com")).json()["refresh_token"]
    other_device = (await _login(api, "a@example.com")).json()["refresh_token"]
    rotated = (await api.post("/auth/refresh", json={"refresh_token": stolen})).json()

    replay = await api.post("/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401
    # Both the thief's new token and every other open session stop working.
    for token in (rotated["refresh_token"], other_device):
        r = await api.post("/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 401
    open_tokens = await session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.used_at.is_(None))
    )
    assert list(open_tokens.scalars()) == []
    [row] = await _audit(session, "REFRESH_TOKEN_REUSE")
    assert (row.user_id, row.result) == (user_id, "FAILURE")
    assert_logged(caplog, "refresh_token_reuse", level="warning", user_id=str(user_id))


async def test_inactive_user_cannot_refresh(api: httpx.AsyncClient, session: AsyncSession) -> None:
    user = await make_user(session, email="a@example.com")
    refresh = (await _login(api, "a@example.com")).json()["refresh_token"]
    user.is_active = False
    await session.flush()
    r = await api.post("/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401


async def test_expired_refresh_token_is_rejected(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="a@example.com")
    refresh = (await _login(api, "a@example.com")).json()["refresh_token"]
    with time_machine.travel(datetime.now(UTC) + timedelta(hours=24, minutes=1)):
        r = await api.post("/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401


async def test_forged_refresh_token_is_rejected(api: httpx.AsyncClient) -> None:
    exp = datetime.now(UTC) + timedelta(hours=1)
    forged = jwt.encode(
        {"sub": "x", "type": "refresh", "jti": "y", "exp": exp},
        "not-the-secret-but-long-enough-for-hs256",
        "HS256",
    )
    assert (await api.post("/auth/refresh", json={"refresh_token": forged})).status_code == 401
    secret = get_settings().jwt_secret
    assert secret is not None
    unknown = jwt.encode(
        {"sub": "x", "type": "refresh", "jti": "not-a-uuid", "exp": exp},
        secret.get_secret_value(),
        "HS256",
    )
    assert (await api.post("/auth/refresh", json={"refresh_token": unknown})).status_code == 401


async def test_change_password_closes_open_sessions(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, email="a@example.com")
    refresh = (await _login(api, "a@example.com")).json()["refresh_token"]
    r = await api.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "brand-new-password"},
        headers=auth_header(user),
    )
    assert r.status_code == 204
    assert (await api.post("/auth/refresh", json={"refresh_token": refresh})).status_code == 401
    assert (await _login(api, "a@example.com")).status_code == 401
    assert (await _login(api, "a@example.com", "brand-new-password")).status_code == 200
    # A revoked token is a plain 401, not a reuse alarm that would close the new session.
    assert await _audit(session, "REFRESH_TOKEN_REUSE") == []
    assert [r.result for r in await _audit(session, "PASSWORD_CHANGED")] == ["SUCCESS"]


async def test_new_password_is_validated(api: httpx.AsyncClient, session: AsyncSession) -> None:
    headers = auth_header(await make_user(session))
    for bad in ("short", "é" * 40):  # < 8 characters; > 72 bytes
        r = await api.post(
            "/auth/change-password",
            json={"current_password": PASSWORD, "new_password": bad},
            headers=headers,
        )
        assert r.status_code == 422


# --- per-email login throttle (D-033 #7) ---


async def _fail(api: httpx.AsyncClient, email: str, times: int) -> None:
    for _ in range(times):
        assert (await _login(api, email, "wrong-password")).status_code == 401


async def test_tenth_failure_blocks_even_the_right_password(
    api: httpx.AsyncClient, session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    await make_user(session, email="owner@example.com")
    await _fail(api, "owner@example.com", 10)
    r = await _login(api, "owner@example.com")
    assert r.status_code == 429
    assert r.json()["code"] == "RATE_LIMITED"
    assert [row.result for row in await _audit(session, "LOGIN")][-1] == "THROTTLED"
    assert_logged(caplog, "login_throttled", level="warning", email="owner@example.com")


async def test_nine_failures_do_not_block(api: httpx.AsyncClient, session: AsyncSession) -> None:
    await make_user(session, email="owner@example.com")
    await _fail(api, "owner@example.com", 9)
    assert (await _login(api, "owner@example.com")).status_code == 200


async def test_differently_written_emails_share_one_limit(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="owner@example.com")
    await _fail(api, "Owner@Example.com", 5)
    await _fail(api, " owner@example.com ", 5)
    assert (await _login(api, "OWNER@example.com")).status_code == 429


async def test_throttle_answers_the_same_for_unknown_emails(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="owner@example.com")
    await _fail(api, "owner@example.com", 10)
    await _fail(api, "nobody@example.com", 10)
    known = await _login(api, "owner@example.com")
    unknown = await _login(api, "nobody@example.com")
    assert known.status_code == unknown.status_code == 429
    assert known.content == unknown.content


async def test_block_lapses_after_15_minutes_even_under_attack(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="owner@example.com")
    await _fail(api, "owner@example.com", 10)
    for _ in range(20):  # the attacker keeps trying; throttled attempts do not extend it
        assert (await _login(api, "owner@example.com", "wrong-password")).status_code == 429
    with time_machine.travel(datetime.now(UTC) + timedelta(minutes=16)):
        assert (await _login(api, "owner@example.com")).status_code == 200


async def test_other_emails_are_not_blocked(api: httpx.AsyncClient, session: AsyncSession) -> None:
    company = await make_company(session)
    await make_user(session, company, email="owner@example.com")
    await make_user(session, company, email="other@example.com")
    await _fail(api, "owner@example.com", 10)
    assert (await _login(api, "other@example.com")).status_code == 200
