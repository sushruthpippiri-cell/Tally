"""Access control for EVERY route, found automatically (RBAC-1.1, SEC-1.2, AC-60).

Routes added in later phases are covered without editing this file:
- a path containing `{company_id}` is company-scoped and must depend on exactly one
  `require(Permission.X)`; a user from another company gets 403, and so does every role
  SRS 14.1 does not allow (the matrix is pinned in tests/core/test_permissions.py);
- any other route must be listed in NON_COMPANY_ROUTES below, so adding a public,
  user-level or Agent-credential route is a deliberate, reviewed choice.

Two halves, so a route is wrong in neither direction: the tests above prove each route
enforces the permission it *declares*, and test_every_route_declares_the_permission_srs_19_2_names
(P16.1) proves the declared permission is the one SRS 19.2 names.
"""

import uuid
from collections.abc import Iterator
from typing import Any, Literal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from pydantic import BaseModel
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
    ("POST", "/auth/refresh"): "public",  # authenticated by the HttpOnly refresh cookie (D-051)
    ("POST", "/auth/logout"): "public",  # closes the session named by the refresh cookie
    ("GET", "/openapi.json"): "public",  # API schema; no data
    ("GET", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("GET", "/redoc"): "public",
    ("POST", "/agent/register"): "public",  # authenticated by the one-time registration token
    ("POST", "/agent/heartbeat"): "agent",  # SRS 19.2: Agent credential
    ("POST", "/agent/commands/{command_id}/claim"): "agent",
    ("POST", "/agent/commands/{command_id}/progress"): "agent",
    ("POST", "/agent/commands/{command_id}/result"): "agent",
    ("POST", "/agent/commands/{command_id}/runs"): "agent",
    ("POST", "/agent/commands/{command_id}/runs/{sync_run_id}/finish"): "agent",
    ("POST", "/agent/leases/acquire"): "agent",
    ("POST", "/agent/leases/renew"): "agent",
    ("POST", "/agent/leases/release"): "agent",
    ("POST", "/agent/commands/{command_id}/batches"): "agent",
    ("POST", "/agent/commands/{command_id}/key-lists"): "agent",
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
@pytest.mark.req("SEC-1.7")
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


@pytest.mark.req("AC-59", "AC-60", "RBAC-1.1", "SEC-1.2")
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


# Every route a user's token opens, except the one that ends the requirement (D-052).
PASSWORD_GATED = [
    e
    for e in ENDPOINTS
    if _access(e) not in ("public", "agent") and e[1] != "/auth/change-password"
]


@pytest.mark.parametrize("endpoint", PASSWORD_GATED, ids=_id)
async def test_an_initial_password_opens_nothing_but_change_password(
    api: httpx.AsyncClient,
    session: AsyncSession,
    companies: tuple[Company, Company],
    endpoint: tuple[str, str, RouteContext],
) -> None:
    """D-052: enforced by the API on every route, not only hidden by the UI. OWNER holds every
    permission, so only the password requirement can refuse."""
    _, b = companies
    user = await make_user(session, b, RoleName.OWNER)
    user.must_change_password = True
    method, path, _ = endpoint
    r = await _call(api, method, _url(path, b.company_id), auth_header(user))
    assert (r.status_code, r.json()["code"]) == (403, "PASSWORD_CHANGE_REQUIRED"), r.text


@pytest.mark.req_partial("SEC-2.0a")  # every Agent route needs the bearer; long random: P3.1
@pytest.mark.parametrize("endpoint", AGENT_ROUTES, ids=_id)
@pytest.mark.req("SEC-1.8")
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
@pytest.mark.req("NFR-SCALE-1")
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


def test_every_agent_endpoint_is_documented_in_openapi() -> None:
    """P3 definition of done: the OpenAPI spec documents every Agent endpoint."""
    spec = create_app().openapi()
    agent_paths = {p for p in spec["paths"] if p.startswith("/agent/")}
    assert agent_paths == {p for _, p, _ in AGENT_ROUTES} | {"/agent/register"}
    for path in agent_paths:
        for operation in spec["paths"][path].values():
            assert operation.get("summary"), f"{path} has no summary"
            assert "agent protocol" in operation["tags"]


# --- the declared permission is the one SRS 19.2 names (AC-59) --------------------------

# SRS 19.2's Access column, transcribed by hand and grouped under its own row headings, so this
# table is the specification rather than a copy of the code - the same way
# tests/core/test_permissions.py pins the SRS 14.1 matrix. Routes SRS 19.2 does not list
# individually carry the decision that added them.
_ANY = frozenset(RoleName)  # SRS "JWT": any signed-in user of the company
_OWNER_ADMIN = frozenset({RoleName.OWNER, RoleName.ADMIN})
_OWNER_ACCOUNTANT = frozenset({RoleName.OWNER, RoleName.ACCOUNTANT})
_OWNER = frozenset({RoleName.OWNER})

SRS_19_2: dict[tuple[str, str], frozenset[RoleName]] = {
    # Not listed row by row in 19.2: the company itself. Reading it is JWT, changing it is a
    # settings change.
    ("GET", "/companies/{company_id}"): _ANY,
    ("PUT", "/companies/{company_id}"): _OWNER_ADMIN,
    # "Users - GET/POST/PUT /companies/{id}/users - Owner"
    ("GET", "/companies/{company_id}/users"): _OWNER,
    ("POST", "/companies/{company_id}/users"): _OWNER,
    ("PUT", "/companies/{company_id}/users/{user_id}"): _OWNER,
    # "Settings and flags - GET/PUT /companies/{id}/settings - Owner/Admin to change"
    ("GET", "/companies/{company_id}/settings"): _ANY,
    ("PUT", "/companies/{company_id}/settings"): _OWNER_ADMIN,
    # "Custom field mappings - GET/PUT /companies/{id}/settings/custom-fields - Owner/Admin"
    ("GET", "/companies/{company_id}/settings/custom-fields"): _OWNER_ADMIN,
    ("PUT", "/companies/{company_id}/settings/custom-fields"): _OWNER_ADMIN,
    ("GET", "/companies/{company_id}/settings/custom-fields/tdl"): _OWNER_ADMIN,
    # "Registration token - POST .../agents/register-token - Owner/Admin"
    ("POST", "/companies/{company_id}/agents/register-token"): _OWNER_ADMIN,
    # "List Agents - GET /companies/{id}/agents - JWT"
    ("GET", "/companies/{company_id}/agents"): _ANY,
    # "Rotate / revoke Agent - Owner/Admin"; "Agent Tally settings - Owner/Admin"
    ("POST", "/companies/{company_id}/agents/{agent_id}/rotate-credential"): _OWNER_ADMIN,
    ("POST", "/companies/{company_id}/agents/{agent_id}/revoke"): _OWNER_ADMIN,
    ("PUT", "/companies/{company_id}/agents/{agent_id}/tally-settings"): _OWNER_ADMIN,
    # "Manual sync - POST .../sync - Owner/Accountant/Admin"
    ("POST", "/companies/{company_id}/sync"): _ANY,
    ("POST", "/companies/{company_id}/agents/{agent_id}/sync"): _ANY,
    # "Schedules - GET/POST/PUT /companies/{id}/sync-schedules - Owner/Admin"
    ("GET", "/companies/{company_id}/sync-schedules"): _OWNER_ADMIN,
    ("POST", "/companies/{company_id}/sync-schedules"): _OWNER_ADMIN,
    ("PUT", "/companies/{company_id}/sync-schedules/{schedule_id}"): _OWNER_ADMIN,
    # "Sync status, errors, lease status - JWT (errors: Owner/Admin)". A command and the run
    # list are the same status family; the key-list confirmation is a D-041 addition that
    # changes what sync treats as deleted, so it sits with settings.
    ("GET", "/companies/{company_id}/sync/status"): _ANY,
    ("GET", "/companies/{company_id}/sync/lease-status"): _ANY,
    ("GET", "/companies/{company_id}/sync/runs"): _ANY,
    ("GET", "/companies/{company_id}/commands/{command_id}"): _ANY,
    ("GET", "/companies/{company_id}/sync/errors"): _OWNER_ADMIN,
    ("POST", "/companies/{company_id}/sync/key-lists/{list_id}/confirm"): _OWNER_ADMIN,
    # "Data quality - GET /companies/{id}/data-quality - JWT"
    ("GET", "/companies/{company_id}/data-quality"): _ANY,
    ("GET", "/companies/{company_id}/data-quality/{check_id}"): _ANY,
    # "Masters - GET /companies/{id}/masters/groups, /voucher-types - JWT"
    ("GET", "/companies/{company_id}/masters/groups"): _ANY,
    ("GET", "/companies/{company_id}/masters/voucher-types"): _ANY,
    ("GET", "/companies/{company_id}/masters/options"): _ANY,
    # "Analytics - GET /companies/{id}/analytics/{metric} (...) - JWT"; "Drill-down - JWT".
    # The named metrics are the same row: 19.2 lists them inside {metric}.
    ("GET", "/companies/{company_id}/analytics/{metric}"): _ANY,
    ("GET", "/companies/{company_id}/analytics/{metric}/drilldown"): _ANY,
    ("GET", "/companies/{company_id}/analytics/customers"): _ANY,
    ("GET", "/companies/{company_id}/analytics/suppliers"): _ANY,
    ("GET", "/companies/{company_id}/analytics/products"): _ANY,
    ("GET", "/companies/{company_id}/analytics/aging"): _ANY,
    ("GET", "/companies/{company_id}/analytics/aging/bills"): _ANY,
    ("GET", "/companies/{company_id}/analytics/aging/allocations"): _ANY,
    ("GET", "/companies/{company_id}/analytics/payment-behaviour"): _ANY,
    ("GET", "/companies/{company_id}/analytics/stock"): _ANY,
    # "Voucher detail - GET /companies/{id}/vouchers/{voucher_id} - JWT"
    ("GET", "/companies/{company_id}/vouchers/{voucher_id}"): _ANY,
    # "Exports - GET /companies/{id}/exports/{report}?format=csv|pdf - JWT"
    ("GET", "/companies/{company_id}/exports/{report}"): _ANY,
    # "Reconciliation - GET .../reconciliation; POST .../reconciliation/run - JWT"
    ("GET", "/companies/{company_id}/reconciliation"): _ANY,
    ("POST", "/companies/{company_id}/reconciliation/run"): _ANY,
    # "Anomalies - GET /companies/{id}/anomalies; POST .../review - JWT; review
    # Owner/Accountant". The other two are D-055: the disclosure is what the Owner must read
    # before enabling the feature (#7), and the discard counts are for Owners/Admins (#3).
    ("GET", "/companies/{company_id}/anomalies"): _ANY,
    ("POST", "/companies/{company_id}/anomalies/{anomaly_id}/review"): _OWNER_ACCOUNTANT,
    ("GET", "/companies/{company_id}/anomalies/disclosure"): _OWNER_ADMIN,
    ("GET", "/companies/{company_id}/anomalies/explanation-health"): _OWNER_ADMIN,
    # Not in 19.2: reading the audit trail is a log view (LOG-1.1).
    ("GET", "/companies/{company_id}/audit"): _OWNER_ADMIN,
}


def _roles_with(permission: Permission) -> frozenset[RoleName]:
    return frozenset(r for r, held in ROLE_PERMISSIONS.items() if permission in held)


def deviations(
    routes: list[tuple[str, str, RouteContext]],
    table: dict[tuple[str, str], frozenset[RoleName]],
) -> tuple[list[str], list[str], list[str]]:
    """(looser than the table, stricter than it, not in it) for each route's declared
    permission."""
    looser, stricter, unclassified = [], [], []
    for method, path, ctx in routes:
        if (method, path) not in table:
            unclassified.append(f"{method} {path}")
            continue
        allowed = table[(method, path)]
        declared = _roles_with(_requires(ctx)[0].permission)
        if extra := declared - allowed:
            looser.append(f"{method} {path}: also allows {sorted(r.value for r in extra)}")
        if missing := allowed - declared:
            stricter.append(f"{method} {path}: SRS allows {sorted(r.value for r in missing)}")
    return looser, stricter, unclassified


@pytest.mark.req("AC-59", "SEC-1.2", "RBAC-1.1")
def test_every_route_declares_the_permission_srs_19_2_names() -> None:
    """Closes this file's stated ceiling: the tests above prove a route enforces the permission
    it declares, this one proves the declared permission is the right one.

    Looser than SRS 19.2 is a hole and fails. Stricter is safe, so it is reported rather than
    failed - a deliberate one belongs in the list below with its reason, and in
    docs/security-review.md. There are none today: all 50 company routes agree with 19.2.
    """
    looser, stricter, unclassified = deviations(COMPANY_ROUTES, SRS_19_2)
    # A new route is classified against the SRS here before it can ship.
    assert unclassified == []
    assert looser == []
    assert stricter == []


def test_the_srs_19_2_guard_catches_a_hole_and_an_omission() -> None:
    """The guard itself fails on bad input (the mutation check stays in the suite, as in
    tests/analytics/test_architecture.py)."""
    settings = [e for e in COMPANY_ROUTES if e[1].endswith("/settings") and e[0] == "PUT"]
    assert settings, "PUT /settings should exist"
    # PUT /settings declares MANAGE_SETTINGS (Owner/Admin). Claiming the SRS said Owner only
    # makes it looser; claiming the SRS said any role makes it stricter.
    looser, stricter, _ = deviations(settings, {("PUT", settings[0][1]): _OWNER})
    assert looser and "ADMIN" in looser[0] and not stricter
    looser, stricter, _ = deviations(settings, {("PUT", settings[0][1]): _ANY})
    assert stricter and "ACCOUNTANT" in stricter[0] and not looser
    # An unlisted route is reported rather than silently passing.
    assert deviations(settings, {})[2] == [f"PUT {settings[0][1]}"]


# --- every request body is a Pydantic model (SEC-1.10, CLAUDE.md rule 14) ---------------


@pytest.mark.req("SEC-1.10")
def test_every_request_body_is_a_pydantic_model() -> None:
    """A dict or a bare `str` body would be unvalidated input reaching a service. FastAPI tells
    us which parameters it treats as the body, so this needs no source scanning."""
    offenders = []
    for method, path, ctx in ENDPOINTS:
        if not isinstance(ctx.original_route, APIRoute):
            continue
        for field in ctx.dependant.body_params:
            annotation = field.field_info.annotation
            origin = getattr(annotation, "__origin__", annotation)
            if isinstance(origin, type) and issubclass(origin, BaseModel):
                continue
            # An uploaded file is not a JSON body and has no schema to validate.
            if annotation is not None and "UploadFile" in str(annotation):
                continue
            offenders.append(f"{method} {path}: {field.name}: {annotation}")
    assert offenders == [], f"request bodies that are not Pydantic models: {offenders}"
