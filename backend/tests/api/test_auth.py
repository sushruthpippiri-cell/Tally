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


def _cookie(r: httpx.Response) -> str:
    """The refresh token from the Set-Cookie header (D-051 #1: never in the body)."""
    for header in r.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        if name == "tally_refresh":
            return rest.split(";", 1)[0]
    raise AssertionError(f"no refresh cookie in {r.headers.get_list('set-cookie')}")


async def _refresh(api: httpx.AsyncClient, token: str, **headers: str) -> httpx.Response:
    return await api.post(
        "/auth/refresh",
        headers={"Cookie": f"tally_refresh={token}", "X-Tally-Request": "1", **headers},
    )


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
    assert "refresh_token" not in body  # D-051 #1: only in the HttpOnly cookie
    access, refresh = _claims(body["access_token"]), _claims(_cookie(r))
    assert access["sub"] == refresh["sub"] == str(user.user_id)
    assert access["type"] == "access" and refresh["type"] == "refresh"
    assert float(str(access["exp"])) - now <= 30 * 60 + 5
    assert float(str(refresh["exp"])) - now <= 24 * 3600 + 5
    assert body["expires_in"] == 1800
    assert user.password_hash.startswith("$2b$")  # bcrypt
    rotated = await _refresh(api, _cookie(r))
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
    refresh = _cookie(await _login(api, "a@example.com"))
    r = await api.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-1"},
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert r.status_code == 401


async def test_refresh_rotates_the_token(api: httpx.AsyncClient, session: AsyncSession) -> None:
    await make_user(session, email="a@example.com")
    first = _cookie(await _login(api, "a@example.com"))
    r = await _refresh(api, first)
    assert r.status_code == 200, r.text
    second = _cookie(r)
    assert second != first
    again = await _refresh(api, second)
    assert again.status_code == 200


async def test_reused_refresh_token_revokes_every_open_token(
    api: httpx.AsyncClient, session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    user_id = (await make_user(session, email="a@example.com")).user_id  # read before failures
    stolen = _cookie(await _login(api, "a@example.com"))
    other_device = _cookie(await _login(api, "a@example.com"))
    rotated = _cookie(await _refresh(api, stolen))

    replay = await _refresh(api, stolen)
    assert replay.status_code == 401
    # Both the thief's new token and every other open session stop working.
    for token in (rotated, other_device):
        r = await _refresh(api, token)
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
    refresh = _cookie(await _login(api, "a@example.com"))
    user.is_active = False
    await session.flush()
    r = await _refresh(api, refresh)
    assert r.status_code == 401


async def test_expired_refresh_token_is_rejected(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="a@example.com")
    refresh = _cookie(await _login(api, "a@example.com"))
    with time_machine.travel(datetime.now(UTC) + timedelta(hours=24, minutes=1)):
        r = await _refresh(api, refresh)
    assert r.status_code == 401


async def test_forged_refresh_token_is_rejected(api: httpx.AsyncClient) -> None:
    exp = datetime.now(UTC) + timedelta(hours=1)
    forged = jwt.encode(
        {"sub": "x", "type": "refresh", "jti": "y", "exp": exp},
        "not-the-secret-but-long-enough-for-hs256",
        "HS256",
    )
    assert (await _refresh(api, forged)).status_code == 401
    secret = get_settings().jwt_secret
    assert secret is not None
    unknown = jwt.encode(
        {"sub": "x", "type": "refresh", "jti": "not-a-uuid", "exp": exp},
        secret.get_secret_value(),
        "HS256",
    )
    assert (await _refresh(api, unknown)).status_code == 401


async def test_change_password_closes_open_sessions(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, email="a@example.com")
    refresh = _cookie(await _login(api, "a@example.com"))
    r = await api.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "brand-new-password"},
        headers=auth_header(user),
    )
    assert r.status_code == 200
    assert _cookie(r) != refresh  # the caller's new session
    assert (await _refresh(api, refresh)).status_code == 401
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


# --- the refresh cookie and CSRF (D-051 #1, #2, SEC-1.5) ---


def _attributes(r: httpx.Response) -> set[str]:
    [header] = [h for h in r.headers.get_list("set-cookie") if h.startswith("tally_refresh=")]
    return {part.strip().lower() for part in header.split(";")[1:]}


async def test_the_refresh_token_is_an_httponly_strict_cookie_for_the_auth_path_only(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="a@example.com")
    r = await _login(api, "a@example.com")
    assert _attributes(r) >= {
        "httponly",
        "secure",
        "samesite=strict",
        "path=/api/auth",
        f"max-age={24 * 3600}",
    }
    assert r.headers["cache-control"] == "no-store"
    assert set(r.json()) == {"access_token", "token_type", "expires_in", "must_change_password"}
    rotated = await _refresh(api, _cookie(r))
    assert _attributes(rotated) >= {"httponly", "secure", "samesite=strict", "path=/api/auth"}
    assert "refresh_token" not in rotated.json()


@pytest.mark.req("SEC-1.5")
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"X-Tally-Request": ""}, 403),  # no custom header: a cross-site form
        ({"Origin": "https://evil.example"}, 403),  # another site
        ({"Origin": "http://test"}, 200),  # this site (Host: test)
        ({}, 200),  # no Origin at all (some same-origin requests)
    ],
)
async def test_the_cookie_endpoints_refuse_cross_site_requests(
    api: httpx.AsyncClient, session: AsyncSession, headers: dict[str, str], status: int
) -> None:
    """SEC-1.5: the only cookie-based endpoints need the X-Tally-Request header and, when an
    Origin is sent, this site's; every other endpoint takes a bearer token only."""
    await make_user(session, email="a@example.com")
    token = _cookie(await _login(api, "a@example.com"))
    r = await _refresh(api, token, **headers)
    assert r.status_code == status, r.text
    if status == 403:
        assert r.json()["code"] == "FORBIDDEN"
        assert (await _refresh(api, token)).status_code == 200  # the token was not spent


async def test_refresh_without_the_cookie_is_401(api: httpx.AsyncClient) -> None:
    r = await api.post("/auth/refresh", headers={"X-Tally-Request": "1"})
    assert (r.status_code, r.json()["code"]) == (401, "NOT_AUTHENTICATED")


async def test_logout_closes_this_session_and_clears_the_cookie(
    api: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, email="a@example.com")
    mine = _cookie(await _login(api, "a@example.com"))
    other = _cookie(await _login(api, "a@example.com"))  # another device stays signed in
    r = await api.post(
        "/auth/logout", headers={"Cookie": f"tally_refresh={mine}", "X-Tally-Request": "1"}
    )
    assert r.status_code == 204
    assert _attributes(r) >= {"max-age=0", "path=/api/auth"}
    assert (await _refresh(api, mine)).status_code == 401
    assert (await _refresh(api, other)).status_code == 200
    assert await _audit(session, "REFRESH_TOKEN_REUSE") == []  # logged out is not stolen
    no_header = await api.post("/auth/logout", headers={"Cookie": f"tally_refresh={other}"})
    assert no_header.status_code == 403


async def test_api_responses_carry_a_no_content_csp(api: httpx.AsyncClient) -> None:
    r = await api.get("/health")
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
