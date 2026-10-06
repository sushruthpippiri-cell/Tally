"""Cross-cutting HTTP concerns (P2.10): CORS (SEC-1.4), rate limits (SEC-1.9), HTTPS (SEC-1.3),
request IDs and security headers. SEC-1.5: bearer tokens only, so no CSRF middleware.

X-Forwarded-For / X-Forwarded-Proto are trusted only from TRUSTED_PROXIES (D-033 #5-6).
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import FastAPI, Request, Response
from starlette.middleware.cors import CORSMiddleware
from structlog.contextvars import bound_contextvars, unbind_contextvars

from app.core.agent_credentials import CREDENTIAL_PREFIX, verified_agent
from app.core.config import Settings
from app.core.errors import AppError, error_response
from app.core.rate_limit import RateLimiter
from app.core.security import decode_token
from tally_contract.errors import ErrorCode

Network = IPv4Network | IPv6Network
ANONYMOUS_PER_MINUTE = 100
USER_PER_MINUTE = 1000
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
HSTS = "max-age=31536000; includeSubDomains"
API_CSP = "default-src 'none'; frame-ancestors 'none'"
_DOCS = ("/docs", "/redoc")  # FastAPI's own pages load scripts; everything else is JSON
# Liveness and readiness probes are not rate-limited: a load balancer polling faster than
# the anonymous limit would be answered 429 and would take the backend out of service
# (P16.11). It also keeps the counter's database round-trip off the liveness path.
_UNLIMITED = ("/health",)


def _trusted(host: str | None, proxies: list[Network]) -> bool:
    try:
        return host is not None and any(ip_address(host) in net for net in proxies)
    except ValueError:
        return False


def client_ip(peer: str | None, forwarded_for: str | None, proxies: list[Network]) -> str:
    """The peer, unless it is a trusted proxy: then the rightmost X-Forwarded-For address that
    is not itself a trusted proxy (addresses further left are client-controlled)."""
    if not _trusted(peer, proxies) or not forwarded_for:
        return peer or "unknown"
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, proxies):
            return hop
    return hops[0] if hops else peer or "unknown"


def effective_scheme(
    scheme: str, peer: str | None, forwarded_proto: str | None, proxies: list[Network]
) -> str:
    if forwarded_proto and _trusted(peer, proxies):
        return forwarded_proto.split(",")[0].strip().lower()
    return scheme


def _rate_key(request: Request, ip: str, config: Settings) -> tuple[str, int]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth[7:].startswith(CREDENTIAL_PREFIX):
        agent_id = verified_agent(auth[7:])  # D-043: only a credential that verified
        if agent_id is not None:
            return f"agent:{agent_id}", config.agent_rate_limit
        return f"ip:{ip}", ANONYMOUS_PER_MINUTE
    if auth.lower().startswith("bearer "):
        try:
            return f"user:{decode_token(auth[7:], 'access')['sub']}", USER_PER_MINUTE
        except AppError:
            pass  # an invalid token counts against the IP
    return f"ip:{ip}", ANONYMOUS_PER_MINUTE


def install_middleware(app: FastAPI, config: Settings) -> None:
    proxies = [ip_network(c, strict=False) for c in config.trusted_proxies]
    limiter = RateLimiter(seconds=config.rate_limit_window_seconds)
    app.state.rate_limiter = limiter  # tests pin its clock
    prod = config.env == "prod"

    @app.middleware("http")
    async def _cross_cutting(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        header_id = request.headers.get("x-request-id", "")
        request_id = header_id if _REQUEST_ID.match(header_id) else uuid.uuid4().hex
        peer = request.client.host if request.client else None
        with bound_contextvars(request_id=request_id):
            try:
                response = await _handle(request, call_next, peer)
            finally:
                # company_id, user_id and agent_id are bound by the dependencies that resolve
                # them (P16.3, SRS 15). Drop them here so they cannot leak into the next
                # request handled by the same task.
                unbind_contextvars("company_id", "user_id", "agent_id")
        response.headers.update(_SECURITY_HEADERS)
        if not request.url.path.startswith(_DOCS):  # the API serves no pages (D-051 #4)
            response.headers["Content-Security-Policy"] = API_CSP
        response.headers["X-Request-ID"] = request_id
        if prod:
            response.headers["Strict-Transport-Security"] = HSTS
        return response

    async def _handle(
        request: Request, call_next: Callable[[Request], Awaitable[Response]], peer: str | None
    ) -> Response:
        if prod:
            proto = request.headers.get("x-forwarded-proto")
            if effective_scheme(request.url.scheme, peer, proto, proxies) != "https":
                return error_response(ErrorCode.HTTPS_REQUIRED, "HTTPS is required", 400)
        if not request.url.path.startswith(_UNLIMITED):
            ip = client_ip(peer, request.headers.get("x-forwarded-for"), proxies)
            key, limit = _rate_key(request, ip, config)
            retry_after = await limiter.hit(key, limit)
            if retry_after is not None:
                return error_response(
                    ErrorCode.RATE_LIMITED,
                    "Too many requests; try again later",
                    429,
                    {"Retry-After": str(retry_after)},
                )
        return await call_next(request)

    # Added last, so it is outermost: preflights are answered and error responses carry CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Tally-Request"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
