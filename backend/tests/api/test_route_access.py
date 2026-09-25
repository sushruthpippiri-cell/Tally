"""Access control for EVERY route, found automatically (RBAC-1.1, SEC-1.2, AC-60).

Routes added in later phases are covered without editing this file:
- a path containing `{company_id}` is company-scoped and must depend on exactly one
  `require(Permission.X)`; a user from another company gets 403, and so does every role
  SRS 14.1 does not allow (the matrix is pinned in tests/core/test_permissions.py);
- any other route must be listed in NON_COMPANY_ROUTES below, so adding a public,
  user-level or Agent-credential route is a deliberate, reviewed choice.

Ceiling: this proves each route enforces the permission it *declares*. Whether that is the
right SRS 19.2 action is proven by that route's own tests (e.g. AC-59 for settings/users);
the write-method guard below catches the commonest slip.
"""

import uuid
from collections.abc import Iterator
from typing import Any, Literal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from app.core.permissions import ROLE_PERMISSIONS, Permission, Require
from app.main import create_app
from app.models.company import Company, User
from app.models.enums import AgentStatus, RoleName
from tests.factories import (
    agent_header,
    auth_header,
    grant,
    make_company,
    make_registered_agent,
    make_user,
)

Access = Literal["public", "user", "agent"]

# Every route that is NOT company-scoped. Adding one here is a security decision: say why.
NON_COMPANY_ROUTES: dict[tuple[str, str], Access] = {
    ("GET", "/health"): "public",  # liveness probe
    ("GET", "/health/db"): "public",  # readiness probe; reveals nothing but up/down
    ("POST", "/auth/login"): "public",  # SRS 19.2
    ("POST", "/auth/refresh"): "public",  # authenticated by the refresh token in the body
    ("GET", "/openapi.json"): "public",  # API schema; no data
    ("GET", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("GET", "/redoc"): "public",
    ("POST", "/agent/register"): "public",  # authenticated by the one-time registration token
    ("POST", "/agent/heartbeat"): "agent",  # SRS 19.2: Agent credential
    ("POST", "/auth/change-password"): "user",  # acts on the caller only
    ("GET", "/companies"): "user",  # lists only the caller's companies
    ("POST", "/companies"): "user",  # D-006: the caller becomes OWNER of the new company
}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
READ_ONLY_PERMISSIONS = {Permission.VIEW_FINANCIALS, Permission.VIEW_RECON_AND_DQ}


def _endpoints(app: FastAPI) -> Iterator[tuple[str, str, RouteContext]]:
    # iter_route_contexts flattens included routers (with their prefixes and router-level
    # dependencies) exactly as FastAPI's OpenAPI generator does.
    for ctx in iter_route_contexts(app.routes):
        if not isinstance(ctx.original_route, Route):  # Mount, WebSocketRoute: decide first
            raise AssertionError(f"unsupported route type: {ctx.original_route!r}")
        assert ctx.path is not None
        for method in sorted((ctx.methods or set()) - {"HEAD"}):
            yield method, ctx.path, ctx


def _calls(dependant: Dependant) -> Iterator[Any]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _calls(sub)


def _requires(ctx: RouteContext) -> list[Require]:
    if not isinstance(ctx.original_route, APIRoute):
        return []
    return [c for c in _calls(ctx.dependant) if isinstance(c, Require)]


ENDPOINTS = list(_endpoints(create_app()))
COMPANY_ROUTES = [(m, p, r) for m, p, r in ENDPOINTS if "{company_id}" in p]
OTHER_ROUTES = [(m, p, r) for m, p, r in ENDPOINTS if "{company_id}" not in p]


def _access(endpoint: tuple[str, str, RouteContext]) -> Access | None:
    return NON_COMPANY_ROUTES.get((endpoint[0], endpoint[1]))


AGENT_ROUTES = [e for e in OTHER_ROUTES if _access(e) == "agent"]
USER_ROUTES = [e for e in OTHER_ROUTES if _access(e) == "user"]


def _id(endpoint: tuple[str, str, RouteContext]) -> str:
    return f"{endpoint[0]} {endpoint[1]}"


def _url(path: str, company_id: uuid.UUID) -> str:
    """Fill {company_id}; every other path parameter gets a random UUID."""
    url = path.replace("{company_id}", str(company_id))
    while "{" in url:
        start, end = url.index("{"), url.index("}")
        url = url[:start] + str(uuid.uuid4()) + url[end + 1 :]
    return url


async def _call(
    api: httpx.AsyncClient, method: str, url: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    # Dependencies (and so require()) run before the body is validated, so `{}` is enough.
    body = {"json": {}} if method in WRITE_METHODS else {}
    return await api.request(method, url, headers=headers or {}, **body)


def _is_forbidden(r: httpx.Response) -> bool:
    return r.status_code == 403 and r.json() == {
        "code": "FORBIDDEN",
        "message": "Not permitted for this company",
        "details": None,
    }


# --- static checks: every route is classified ------------------------------------------


def test_enumeration_found_the_routes() -> None:
    assert len(COMPANY_ROUTES) >= 2, "no company-scoped routes found: enumeration is broken"
    assert ("POST", "/auth/login") in {(m, p) for m, p, _ in ENDPOINTS}
    assert AGENT_ROUTES, "no Agent-credential routes found: enumeration is broken"


@pytest.mark.parametrize("endpoint", COMPANY_ROUTES, ids=_id)
def test_company_route_declares_exactly_one_permission(
    endpoint: tuple[str, str, RouteContext],
) -> None:
    method, path, route = endpoint
    requires = _requires(route)
    assert len(requires) == 1, f"{method} {path} must depend on exactly one require(...)"
    # SEC-1.7: only require() reads company_id; the endpoint uses ctx.company_id.
    assert "company_id" not in {p.name for p in route.dependant.path_params}, (
        f"{method} {path} takes company_id itself; use ctx.company_id"
    )
    if method in WRITE_METHODS:
        assert requires[0].permission not in READ_ONLY_PERMISSIONS, (
            f"{method} {path} changes data but only requires {requires[0].permission}"
        )


@pytest.mark.parametrize("endpoint", OTHER_ROUTES, ids=_id)
def test_non_company_route_is_allow_listed(endpoint: tuple[str, str, RouteContext]) -> None:
    method, path, route = endpoint
    assert (method, path) in NON_COMPANY_ROUTES, (
        f"{method} {path} is not company-scoped: add it to NON_COMPANY_ROUTES with a reason, "
        "or put it under /companies/{company_id}"
    )
    assert _requires(route) == [], f"{method} {path} uses require() without {{company_id}}"


def test_allow_list_has_no_stale_entries() -> None:
    live = {(m, p) for m, p, _ in OTHER_ROUTES}
    assert set(NON_COMPANY_ROUTES) - live == set()


# --- behaviour: every company route --------------------------------------------------


@pytest.fixture
async def companies(session: AsyncSession) -> tuple[Company, Company]:
    return await make_company(session, name="A"), await make_company(session, name="B")


@pytest.mark.req("AC-60", "RBAC-1.1", "SEC-1.2")
@pytest.mark.parametrize("endpoint", COMPANY_ROUTES, ids=_id)
async def test_user_of_another_company_gets_403_and_no_data(
    api: httpx.AsyncClient,
    session: AsyncSession,
    companies: tuple[Company, Company],
    endpoint: tuple[str, str, RouteContext],
) -> None:
    a, b = companies
    # OWNER holds every permission, so a 403 here can only come from tenancy.
    headers = auth_header(await make_user(session, a, RoleName.OWNER))
    method, path, _ = endpoint
    other = await _call(api, method, _url(path, b.company_id), headers)
    missing = await _call(api, method, _url(path, uuid.uuid4()), headers)
    assert _is_forbidden(other), other.text
    # Same answer whether or not the company exists (AC-60).
    assert (missing.status_code, missing.content) == (other.status_code, other.content)


@pytest.mark.req("AC-60", "RBAC-1.1", "SEC-1.2")
@pytest.mark.parametrize("endpoint", COMPANY_ROUTES, ids=_id)
async def test_each_role_gets_exactly_what_srs_14_1_allows(
    api: httpx.AsyncClient,
    session: AsyncSession,
    companies: tuple[Company, Company],
    endpoint: tuple[str, str, RouteContext],
) -> None:
    _, b = companies
    method, path, route = endpoint
    [requirement] = _requires(route)
    for role in RoleName:
        headers = auth_header(await make_user(session, b, role))
        r = await _call(api, method, _url(path, b.company_id), headers)
        if requirement.permission in ROLE_PERMISSIONS[role]:
            assert r.status_code not in (401, 403), f"{role} denied {method} {path}: {r.text}"
        else:
            assert _is_forbidden(r), f"{role} allowed {method} {path}: {r.status_code}"


@pytest.mark.parametrize(
    "endpoint",
    [e for e in ENDPOINTS if NON_COMPANY_ROUTES.get((e[0], e[1])) != "public"],
    ids=_id,
)
async def test_every_non_public_route_needs_a_token(
    api: httpx.AsyncClient, endpoint: tuple[str, str, RouteContext]
) -> None:
    method, path, _ = endpoint
    expected = "CREDENTIAL_INVALID" if _access(endpoint) == "agent" else "NOT_AUTHENTICATED"
    for headers in ({}, {"Authorization": "Bearer not-a-jwt"}):
        r = await _call(api, method, _url(path, uuid.uuid4()), headers)
        assert r.status_code == 401, f"{method} {path}: {r.status_code}"
        assert r.json()["code"] == expected


@pytest.mark.parametrize(
    "endpoint",
    USER_ROUTES,
    ids=_id,
)
async def test_user_routes_accept_any_signed_in_user(
    api: httpx.AsyncClient, session: AsyncSession, endpoint: tuple[str, str, RouteContext]
) -> None:
    method, path, _ = endpoint
    r = await _call(api, method, path, auth_header(await make_user(session)))
    assert r.status_code not in (401, 403), r.text


@pytest.mark.req_partial("SEC-2.0a")  # every Agent route needs the bearer; long random: P3.1
@pytest.mark.parametrize("endpoint", AGENT_ROUTES, ids=_id)
async def test_agent_routes_take_only_a_valid_agent_credential(
    api: httpx.AsyncClient, session: AsyncSession, endpoint: tuple[str, str, RouteContext]
) -> None:
    method, path, _ = endpoint
    company = await make_company(session)
    user_token = auth_header(await make_user(session, company, RoleName.OWNER))
    _, credential = await make_registered_agent(session, company)
    _, revoked = await make_registered_agent(
        session, company, name="revoked", status=AgentStatus.REVOKED
    )
    url = _url(path, uuid.uuid4())
    r = await _call(api, method, url, user_token)
    assert (r.status_code, r.json()["code"]) == (401, "CREDENTIAL_INVALID"), "user JWT accepted"
    r = await _call(api, method, url, agent_header(revoked))
    assert (r.status_code, r.json()["code"]) == (401, "AGENT_REVOKED")
    r = await _call(api, method, url, agent_header(credential))
    assert r.status_code not in (401, 403), f"{method} {path} rejected a valid Agent: {r.text}"


@pytest.mark.parametrize("endpoint", USER_ROUTES + COMPANY_ROUTES, ids=_id)
async def test_user_and_company_routes_reject_agent_credentials(
    api: httpx.AsyncClient, session: AsyncSession, endpoint: tuple[str, str, RouteContext]
) -> None:
    method, path, _ = endpoint
    company = await make_company(session)
    _, credential = await make_registered_agent(session, company)
    r = await _call(api, method, _url(path, company.company_id), agent_header(credential))
    assert (r.status_code, r.json()["code"]) == (401, "NOT_AUTHENTICATED"), r.text


async def test_deactivated_user_is_rejected_on_company_routes(
    api: httpx.AsyncClient, session: AsyncSession, companies: tuple[Company, Company]
) -> None:
    a, _ = companies
    user: User = await make_user(session, a, RoleName.OWNER, is_active=False)
    r = await api.get(f"/companies/{a.company_id}", headers=auth_header(user))
    assert r.status_code == 401


@pytest.mark.req("RBAC-1.2")
async def test_roles_are_held_per_company(
    api: httpx.AsyncClient, session: AsyncSession, companies: tuple[Company, Company]
) -> None:
    a, b = companies
    user = await make_user(session, a, RoleName.OWNER)
    await grant(session, user, b, RoleName.ACCOUNTANT)
    headers = auth_header(user)
    assert (
        await api.put(f"/companies/{a.company_id}", json={}, headers=headers)
    ).status_code == 200
    assert _is_forbidden(await api.put(f"/companies/{b.company_id}", json={}, headers=headers))
    assert (await api.get(f"/companies/{b.company_id}", headers=headers)).status_code == 200
