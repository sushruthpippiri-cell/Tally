"""P2.10: CORS, rate limits, trusted proxies, HTTPS, request IDs, security headers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import ip_network
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.middleware import client_ip, effective_scheme
from app.core.rate_limit import RateLimiter
from app.main import create_app
from tally_contract.testing import assert_logged
from tests.conftest import client_for, counter_store
from tests.factories import (
    agent_header,
    auth_header,
    make_company,
    make_registered_agent,
    make_user,
)

PROXIES = [ip_network("10.0.0.0/8")]
# The limiter runs before routing, so an unrouted path is counted and answers 404. /health
# is exempt (P16.11), so the rate-limit tests cannot use it as their target any more.
LIMITED = "/no-such-path"
LB = ("10.0.0.5", 5000)  # a trusted proxy
STRANGER = ("203.0.113.9", 5000)  # an untrusted peer


@pytest.fixture
async def store() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """For the tests that build a RateLimiter directly, without going through an app."""
    async with counter_store() as maker:
        yield maker


def _config(**kw: Any) -> Settings:
    base: dict[str, Any] = {"env": "test"}
    if kw.get("env") == "prod":
        base |= {
            "database_url": "postgresql+asyncpg://unused",
            "database_migration_url": "postgresql+psycopg://unused",
            "jwt_secret": "p" * 40,
            "cors_origins": "https://app.example",
        }
    return Settings(_env_file=None, **(base | kw))  # type: ignore[call-arg]


@asynccontextmanager
async def _client(
    session: AsyncSession, peer: tuple[str, int] = STRANGER, **config: Any
) -> AsyncIterator[httpx.AsyncClient]:
    base_url = config.pop("base_url", "http://test")
    app = create_app(_config(**config))
    # One fixed instant: a test's requests never straddle a rate-limit window (CLAUDE.md:
    # tests never depend on the real clock).
    app.state.rate_limiter._clock = lambda: 1_000_000.0 + 1
    async with client_for(app, session, client=peer, base_url=base_url) as client:
        yield client


# --- client IP and scheme (D-033 #5-6) -------------------------------------------------


def test_forwarded_for_is_ignored_from_an_untrusted_peer() -> None:
    assert client_ip("203.0.113.9", "1.2.3.4", PROXIES) == "203.0.113.9"
    assert client_ip("203.0.113.9", "1.2.3.4", []) == "203.0.113.9"


def test_forwarded_for_from_a_trusted_proxy_gives_the_real_client() -> None:
    assert client_ip("10.0.0.5", "1.2.3.4", PROXIES) == "1.2.3.4"
    # Addresses left of the one our proxy appended are client-controlled.
    assert client_ip("10.0.0.5", "6.6.6.6, 1.2.3.4, 10.0.0.7", PROXIES) == "1.2.3.4"
    assert client_ip("10.0.0.5", None, PROXIES) == "10.0.0.5"


def test_forwarded_proto_counts_only_from_a_trusted_proxy() -> None:
    assert effective_scheme("http", "203.0.113.9", "https", PROXIES) == "http"
    assert effective_scheme("http", "10.0.0.5", "https", PROXIES) == "https"
    assert effective_scheme("http", "10.0.0.5", "HTTP", PROXIES) == "http"
    assert effective_scheme("https", "203.0.113.9", None, PROXIES) == "https"


def test_trusted_proxies_must_be_networks() -> None:
    with pytest.raises(ValueError, match="does not appear to be an IPv4 or IPv6 network"):
        _config(trusted_proxies="10.0.0.0/8, not-a-network")
    assert _config(trusted_proxies="10.0.0.0/8, 192.168.1.1").trusted_proxies == [
        "10.0.0.0/8",
        "192.168.1.1",
    ]


# --- rate limits (SEC-1.9) -------------------------------------------------------------


async def test_limiter_windows_reset_each_minute(
    store: async_sessionmaker[AsyncSession],
) -> None:
    now = [120.0]
    limiter = RateLimiter(clock=lambda: now[0], factory=store)
    assert [await limiter.hit("k", 2) for _ in range(2)] == [None, None]
    assert await limiter.hit("k", 2) == 60
    assert await limiter.hit("other", 2) is None
    now[0] = 180.0
    assert await limiter.hit("k", 2) is None


@pytest.mark.req("SEC-1.9")
async def test_two_replicas_share_one_limit(store: async_sessionmaker[AsyncSession]) -> None:
    """P16.11: the whole point of moving the counters to Postgres. Two backends behind one load
    balancer must together allow the limit, not one each - which is what in-process counters
    did, and why production could not run more than one replica."""
    start = 16_666 * 60.0  # the start of a window, so Retry-After is the full 60
    one = RateLimiter(clock=lambda: start, seconds=60, factory=store)
    two = RateLimiter(clock=lambda: start, seconds=60, factory=store)
    allowed = 0
    for _ in range(6):  # alternate, as a load balancer would
        for limiter in (one, two):
            if await limiter.hit("ip:1.2.3.4", 4) is None:
                allowed += 1
    assert allowed == 4
    # A different key is unaffected, and each replica still answers with a Retry-After.
    assert await one.hit("ip:5.6.7.8", 4) is None
    assert await two.hit("ip:1.2.3.4", 4) == 60


async def test_health_is_never_rate_limited(session: AsyncSession) -> None:
    """A load balancer polling faster than the anonymous limit would otherwise be answered 429
    and would take the backend out of service (P16.11)."""
    async with _client(session) as client:
        for _ in range(150):  # well past ANONYMOUS_PER_MINUTE
            assert (await client.get("/health")).status_code == 200
        # The exemption is the path's, not the caller's: the same caller is still limited.
        for _ in range(100):
            assert (await client.get(LIMITED)).status_code == 404
        assert (await client.get(LIMITED)).status_code == 429


@pytest.mark.req("SEC-1.9")
async def test_100_per_minute_per_ip_then_1000_per_user(session: AsyncSession) -> None:
    headers = auth_header(await make_user(session))
    async with _client(session) as client:
        for _ in range(100):
            assert (await client.get(LIMITED)).status_code == 404
        blocked = await client.get(LIMITED)
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "RATE_LIMITED"
        assert 1 <= int(blocked.headers["Retry-After"]) <= 60
        # A signed-in user on the same IP has their own, larger bucket.
        for _ in range(1000):
            assert (await client.get(LIMITED, headers=headers)).status_code == 404
        assert (await client.get(LIMITED, headers=headers)).status_code == 429


async def test_spoofed_forwarded_for_does_not_escape_the_ip_limit(
    session: AsyncSession,
) -> None:
    async with _client(session, STRANGER, trusted_proxies="10.0.0.0/8") as client:
        for i in range(100):
            r = await client.get(LIMITED, headers={"X-Forwarded-For": f"1.1.1.{i}"})
            assert r.status_code == 404
        r = await client.get(LIMITED, headers={"X-Forwarded-For": "9.9.9.9"})
        assert r.status_code == 429


async def test_clients_behind_a_trusted_proxy_get_separate_buckets(
    session: AsyncSession,
) -> None:
    async with _client(session, LB, trusted_proxies="10.0.0.0/8") as client:
        for _ in range(100):
            assert (
                await client.get(LIMITED, headers={"X-Forwarded-For": "1.1.1.1"})
            ).status_code == 404
        assert (
            await client.get(LIMITED, headers={"X-Forwarded-For": "1.1.1.1"})
        ).status_code == 429
        assert (
            await client.get(LIMITED, headers={"X-Forwarded-For": "2.2.2.2"})
        ).status_code == 404


async def test_an_invalid_token_counts_against_the_ip(session: AsyncSession) -> None:
    async with _client(session) as client:
        bad = {"Authorization": "Bearer forged"}
        for _ in range(100):
            await client.get(LIMITED, headers=bad)
        assert (await client.get(LIMITED, headers=bad)).status_code == 429


# --- Agents' own buckets (D-043) --------------------------------------------------------

RENEW = "/agent/leases/renew"  # an authenticated Agent call with no body


async def _agents(session: AsyncSession, n: int) -> list[dict[str, str]]:
    company = await make_company(session)
    return [
        agent_header((await make_registered_agent(session, company, f"agent-{i}"))[1])
        for i in range(n)
    ]


async def test_each_agent_has_its_own_bucket_even_behind_one_office_ip(
    session: AsyncSession,
) -> None:
    a, b = await _agents(session, 2)
    async with _client(session, agent_rate_limit=3) as client:
        assert (await client.post(RENEW, headers=a)).status_code == 200  # verifies: IP bucket
        for _ in range(3):
            assert (await client.post(RENEW, headers=a)).status_code == 200
        blocked = await client.post(RENEW, headers=a)
        assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMITED"
        assert int(blocked.headers["Retry-After"]) >= 1
        for _ in range(4):  # Agent B, same IP, untouched by A
            assert (await client.post(RENEW, headers=b)).status_code == 200
        # A user and an anonymous caller behind the same IP are not starved either.
        user = auth_header(await make_user(session))
        assert (await client.get(LIMITED, headers=user)).status_code == 404
        assert (await client.get(LIMITED)).status_code == 404


async def test_forged_agent_tokens_count_against_the_ip(session: AsyncSession) -> None:
    """Only a credential that verified gets its own bucket: forging `agt_<id>` tokens cannot
    mint fresh ones."""
    import uuid

    async with _client(session) as client:
        for _ in range(100):
            forged = {"Authorization": f"Bearer agt_{uuid.uuid4()}.not-the-secret"}
            assert (await client.post(RENEW, headers=forged)).status_code == 401
        forged = {"Authorization": f"Bearer agt_{uuid.uuid4()}.not-the-secret"}
        assert (await client.post(RENEW, headers=forged)).status_code == 429


async def test_a_cached_bucket_never_authenticates_a_revoked_agent(session: AsyncSession) -> None:
    company = await make_company(session)
    agent, credential = await make_registered_agent(session, company)
    headers = agent_header(credential)
    async with _client(session) as client:
        assert (await client.post(RENEW, headers=headers)).status_code == 200
        agent.status = "REVOKED"
        await session.flush()
        refused = await client.post(RENEW, headers=headers)
        assert (refused.status_code, refused.json()["code"]) == (401, "AGENT_REVOKED")


# --- HTTPS (SEC-1.3) ------------------------------------------------------------------


@pytest.mark.req_partial("SEC-1.3")  # TLS 1.2+ is the reverse proxy's job: P16 deploy
async def test_prod_rejects_plain_http_and_sends_hsts(session: AsyncSession) -> None:
    async with _client(session, env="prod") as client:
        r = await client.get("/health")
        assert r.status_code == 400
        assert r.json()["code"] == "HTTPS_REQUIRED"
    async with _client(session, env="prod", base_url="https://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.headers["Strict-Transport-Security"].startswith("max-age=")


async def test_spoofed_forwarded_proto_from_an_untrusted_peer_is_ignored(
    session: AsyncSession,
) -> None:
    async with _client(session, STRANGER, env="prod", trusted_proxies="10.0.0.0/8") as client:
        r = await client.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert r.status_code == 400


async def test_forwarded_proto_from_a_trusted_proxy_is_honoured(session: AsyncSession) -> None:
    async with _client(session, LB, env="prod", trusted_proxies="10.0.0.0/8") as client:
        assert (
            await client.get("/health", headers={"X-Forwarded-Proto": "https"})
        ).status_code == 200
        assert (
            await client.get("/health", headers={"X-Forwarded-Proto": "http"})
        ).status_code == 400


async def test_dev_accepts_http_without_hsts(session: AsyncSession) -> None:
    async with _client(session) as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert "Strict-Transport-Security" not in r.headers


# --- CORS (SEC-1.4) -------------------------------------------------------------------


@pytest.mark.req("SEC-1.4")
async def test_cors_allows_only_configured_origins(session: AsyncSession) -> None:
    preflight = {
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization",
    }
    async with _client(session, cors_origins="https://app.example") as client:
        ok = await client.options(
            "/companies", headers=preflight | {"Origin": "https://app.example"}
        )
        assert ok.headers["Access-Control-Allow-Origin"] == "https://app.example"
        bad = await client.options(
            "/companies", headers=preflight | {"Origin": "https://evil.example"}
        )
        assert "Access-Control-Allow-Origin" not in bad.headers
        simple = await client.get("/health", headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in simple.headers


# --- request id and headers -----------------------------------------------------------


async def test_request_id_is_echoed_logged_or_generated(
    api: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    r = await api.get("/companies", headers={"X-Request-ID": "req-123"})
    assert r.status_code == 401
    assert r.headers["X-Request-ID"] == "req-123"
    assert_logged(caplog, "app_error", request_id="req-123", code="NOT_AUTHENTICATED")
    generated = await api.get("/health", headers={"X-Request-ID": "bad id\n<script>"})
    assert generated.headers["X-Request-ID"] != "bad id\n<script>"
    assert len(generated.headers["X-Request-ID"]) == 32


async def test_security_headers_on_success_and_error(api: httpx.AsyncClient) -> None:
    for r in (await api.get("/health"), await api.get("/companies")):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
