"""P2.6: users and roles per company (RBAC-1.2, LOG-1.1, D-033 #8-9)."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, User
from app.models.config import AuditLog
from app.models.enums import RoleName
from tests.factories import PASSWORD, auth_header, grant, make_company, make_user


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    return await make_company(session)


@pytest.fixture
async def owner(session: AsyncSession, company: Company) -> User:
    return await make_user(session, company, RoleName.OWNER, email="owner@example.com")


def _users(company: Company) -> str:
    return f"/companies/{company.company_id}/users"


async def _audit(session: AsyncSession) -> list[AuditLog]:
    return list((await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars())


async def test_owner_creates_a_user_who_can_then_log_in(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    r = await api.post(
        _users(company),
        json={
            "email": " New@Example.com",
            "name": "New",
            "password": "initial-pass",
            "roles": ["ACCOUNTANT"],
        },
        headers=auth_header(owner),
    )
    assert r.status_code == 201, r.text
    assert (r.json()["email"], r.json()["roles"]) == ("new@example.com", ["ACCOUNTANT"])
    login = await api.post(
        "/auth/login", json={"email": "new@example.com", "password": "initial-pass"}
    )
    assert login.status_code == 200
    listed = await api.get(_users(company), headers=auth_header(owner))
    assert [(u["email"], u["roles"]) for u in listed.json()] == [
        ("new@example.com", ["ACCOUNTANT"]),
        ("owner@example.com", ["OWNER"]),
    ]
    [row] = [a for a in await _audit(session) if a.action == "USER_CREATED"]
    assert (row.company_id, row.user_id, row.after_value) == (
        company.company_id,
        owner.user_id,
        {"roles": ["ACCOUNTANT"]},
    )


async def test_existing_email_is_attached_and_its_password_kept(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    other = await make_company(session, name="Other")
    await make_user(session, other, RoleName.ACCOUNTANT, email="shared@example.com")
    r = await api.post(
        _users(company),
        json={
            "email": "SHARED@example.com",
            "name": "ignored",
            "password": "ignored-pass",
            "roles": ["ADMIN"],
        },
        headers=auth_header(owner),
    )
    assert r.status_code == 201, r.text
    assert r.json()["roles"] == ["ADMIN"]
    ok = await api.post("/auth/login", json={"email": "shared@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    token = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    mine = await api.get("/companies", headers=token)
    assert {c["name"]: c["my_roles"] for c in mine.json()} == {
        "Other": ["ACCOUNTANT"],
        company.name: ["ADMIN"],
    }
    assert "USER_ATTACHED" in [a.action for a in await _audit(session)]


async def test_adding_an_existing_member_is_a_conflict(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    r = await api.post(
        _users(company),
        json={
            "email": "owner@example.com",
            "name": "x",
            "password": "whatever-1",
            "roles": ["ADMIN"],
        },
        headers=auth_header(owner),
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "name": "x", "password": "long-enough", "roles": ["ADMIN"]},
        {"email": "a@example.com", "name": "x", "password": "short", "roles": ["ADMIN"]},
        {"email": "a@example.com", "name": "x", "password": "long-enough", "roles": []},
        {"email": "a@example.com", "name": "x", "password": "long-enough", "roles": ["ROOT"]},
    ],
)
async def test_invalid_new_user_is_422(
    api: httpx.AsyncClient, company: Company, owner: User, body: dict[str, object]
) -> None:
    r = await api.post(_users(company), json=body, headers=auth_header(owner))
    assert r.status_code == 422


@pytest.mark.req_partial("LOG-1.1")  # user and role changes; other actions in their phases
async def test_roles_are_replaced_and_audited(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    user = await make_user(session, company, RoleName.ACCOUNTANT)
    r = await api.put(
        f"{_users(company)}/{user.user_id}",
        json={"roles": ["ADMIN", "ACCOUNTANT", "ADMIN"]},
        headers=auth_header(owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["ACCOUNTANT", "ADMIN"]
    row = (await _audit(session))[-1]
    assert (row.action, row.entity_id, row.before_value, row.after_value) == (
        "ROLES_CHANGED",
        str(user.user_id),
        {"roles": ["ACCOUNTANT"]},
        {"roles": ["ACCOUNTANT", "ADMIN"]},
    )


async def test_removal_takes_effect_on_the_next_request(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    user = await make_user(session, company, RoleName.ADMIN)
    headers = auth_header(user)  # a token issued while they were Admin
    assert (await api.get(f"/companies/{company.company_id}", headers=headers)).status_code == 200
    r = await api.put(
        f"{_users(company)}/{user.user_id}", json={"roles": []}, headers=auth_header(owner)
    )
    assert r.status_code == 200
    assert (await api.get(f"/companies/{company.company_id}", headers=headers)).status_code == 403
    # Removal is per company: the account itself stays active (D-033 #9).
    assert (await session.get(User, user.user_id)).is_active is True  # type: ignore[union-attr]
    assert (await _audit(session))[-1].action == "ROLES_CHANGED"


async def test_role_removal_does_not_touch_other_companies(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    other = await make_company(session, name="Other")
    user = await make_user(session, company, RoleName.ACCOUNTANT)
    await grant(session, user, other, RoleName.ACCOUNTANT)
    await api.put(
        f"{_users(company)}/{user.user_id}", json={"roles": []}, headers=auth_header(owner)
    )
    r = await api.get(f"/companies/{other.company_id}", headers=auth_header(user))
    assert r.status_code == 200


@pytest.mark.parametrize("new_roles", [[], ["ADMIN"], ["ACCOUNTANT", "ADMIN"]])
async def test_last_owner_cannot_be_removed_or_downgraded_even_by_themselves(
    api: httpx.AsyncClient,
    session: AsyncSession,
    company: Company,
    owner: User,
    new_roles: list[str],
) -> None:
    r = await api.put(
        f"{_users(company)}/{owner.user_id}",
        json={"roles": new_roles},
        headers=auth_header(owner),
    )
    assert r.status_code == 409
    assert r.json()["message"] == "A company must keep at least one Owner"
    still = await api.get(_users(company), headers=auth_header(owner))
    assert still.json()[0]["roles"] == ["OWNER"]


async def test_an_owner_can_step_down_when_another_owner_remains(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    await make_user(session, company, RoleName.OWNER)
    r = await api.put(
        f"{_users(company)}/{owner.user_id}",
        json={"roles": ["ADMIN"]},
        headers=auth_header(owner),
    )
    assert r.status_code == 200


async def test_users_of_other_companies_are_not_found(
    api: httpx.AsyncClient, session: AsyncSession, company: Company, owner: User
) -> None:
    stranger = await make_user(session, await make_company(session), RoleName.OWNER)
    r = await api.put(
        f"{_users(company)}/{stranger.user_id}",
        json={"roles": ["ADMIN"]},
        headers=auth_header(owner),
    )
    assert r.status_code == 404
    listed = await api.get(_users(company), headers=auth_header(owner))
    assert [u["email"] for u in listed.json()] == ["owner@example.com"]
