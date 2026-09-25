"""P2.10: CORS, rate limits, trusted proxies, HTTPS, request IDs, security headers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import ip_network
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.middleware import RateLimiter, client_ip, effective_scheme
from app.main import create_app
from tally_contract.testing import assert_logged
from tests.conftest import client_for
from tests.factories import auth_header, make_user

PROXIES = [ip_network("10.0.0.0/8")]
LB = ("10.0.0.5", 5000)  # a trusted proxy
STRANGER = ("203.0.113.9", 5000)  # an untrusted peer


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
    async with client_for(
        create_app(_config(**config)), session, client=peer, base_url=base_url
    ) as client:
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


def test_limiter_windows_reset_each_minute() -> None:
    now = [120.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert all(limiter.hit("k", 2) is None for _ in range(2))
    assert limiter.hit("k", 2) == 60
    assert limiter.hit("other", 2) is None
    now[0] = 180.0
    assert limiter.hit("k", 2) is None


@pytest.mark.req("SEC-1.9")
async def test_100_per_minute_per_ip_then_1000_per_user(session: AsyncSession) -> None:
    headers = auth_header(await make_user(session))
    async with _client(session) as client:
        for _ in range(100):
            assert (await client.get("/health")).status_code == 200
        blocked = await client.get("/health")
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "RATE_LIMITED"
        assert 1 <= int(blocked.headers["Retry-After"]) <= 60
        # A signed-in user on the same IP has their own, larger bucket.
        for _ in range(1000):
            assert (await client.get("/health", headers=headers)).status_code == 200
        assert (await client.get("/health", headers=headers)).status_code == 429


async def test_spoofed_forwarded_for_does_not_escape_the_ip_limit(
    session: AsyncSession,
) -> None:
    async with _client(session, STRANGER, trusted_proxies="10.0.0.0/8") as client:
        for i in range(100):
            r = await client.get("/health", headers={"X-Forwarded-For": f"1.1.1.{i}"})
            assert r.status_code == 200
        r = await client.get("/health", headers={"X-Forwarded-For": "9.9.9.9"})
        assert r.status_code == 429


async def test_clients_behind_a_trusted_proxy_get_separate_buckets(
    session: AsyncSession,
) -> None:
    async with _client(session, LB, trusted_proxies="10.0.0.0/8") as client:
        for _ in range(100):
            assert (
                await client.get("/health", headers={"X-Forwarded-For": "1.1.1.1"})
            ).status_code == 200
        assert (
            await client.get("/health", headers={"X-Forwarded-For": "1.1.1.1"})
        ).status_code == 429
        assert (
            await client.get("/health", headers={"X-Forwarded-For": "2.2.2.2"})
        ).status_code == 200


async def test_an_invalid_token_counts_against_the_ip(session: AsyncSession) -> None:
    async with _client(session) as client:
        bad = {"Authorization": "Bearer forged"}
        for _ in range(100):
            await client.get("/health", headers=bad)
        assert (await client.get("/health", headers=bad)).status_code == 429


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
