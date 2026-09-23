"""P1.2: companies, users, roles, user_roles (SRS 5.3)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Role, User, UserRole
from app.models.enums import RoleName
from tests.factories import db_error, guid, make_company


async def test_roles_are_seeded(session: AsyncSession) -> None:
    names = set((await session.scalars(select(Role.role_name))).all())
    assert names == {r.value for r in RoleName}


async def test_company_tally_guid_is_unique_but_nullable(session: AsyncSession) -> None:
    await make_company(session)
    await make_company(session)  # two companies before any Agent registers
    g = guid()
    await make_company(session, tally_guid=g)
    async with db_error(session, "uq_companies_tally_guid"):
        await make_company(session, tally_guid=g)


async def test_email_is_unique_ignoring_case(session: AsyncSession) -> None:
    session.add(User(email="owner@example.com", password_hash="x", name="Owner"))
    await session.flush()
    async with db_error(session, "uq_users_email_lower"):
        session.add(User(email="Owner@Example.com", password_hash="x", name="Owner 2"))
        await session.flush()


async def test_user_role_is_unique_per_company(session: AsyncSession) -> None:
    company = await make_company(session)
    user = User(email=f"{guid()}@example.com", password_hash="x", name="U")
    session.add(user)
    await session.flush()
    owner = await session.scalar(select(Role.role_id).where(Role.role_name == RoleName.OWNER))
    assert owner is not None
    session.add(UserRole(user_id=user.user_id, company_id=company.company_id, role_id=owner))
    await session.flush()
    async with db_error(session, "pk_user_roles"):
        await session.execute(
            text("INSERT INTO user_roles VALUES (:u, :c, :r)"),
            {"u": user.user_id, "c": company.company_id, "r": owner},
        )


@pytest.mark.parametrize("bad", ["SUPERUSER", "owner"])
async def test_unknown_role_name_rejected(session: AsyncSession, bad: str) -> None:
    async with db_error(session, "ck_roles_role_name"):
        await session.execute(text("INSERT INTO roles VALUES (99, :n)"), {"n": bad})
