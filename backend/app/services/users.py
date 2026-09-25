"""Users and their roles in one company (MANAGE_USERS, RBAC-1.2, D-033 #8-9)."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import AppError
from app.core.permissions import CompanyContext
from app.core.security import hash_password
from app.models.company import Company, Role, User, UserRole
from app.models.enums import RoleName
from app.schemas.users import CompanyUserOut, RolesUpdate, UserCreate
from app.services.companies import role_id
from tally_contract.errors import ErrorCode


async def _roles_in(
    session: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> dict[uuid.UUID, list[RoleName]]:
    stmt = (
        select(UserRole.user_id, Role.role_name)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(UserRole.company_id == company_id)
        .order_by(Role.role_name)
    )
    if user_id is not None:
        stmt = stmt.where(UserRole.user_id == user_id)
    roles: dict[uuid.UUID, list[RoleName]] = {}
    for uid, name in (await session.execute(stmt)).tuples():
        roles.setdefault(uid, []).append(RoleName(name))
    return roles


def _out(user: User, roles: list[RoleName]) -> CompanyUserOut:
    return CompanyUserOut(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        roles=roles,
    )


async def list_users(session: AsyncSession, ctx: CompanyContext) -> list[CompanyUserOut]:
    roles = await _roles_in(session, ctx.company_id)
    users = await session.execute(select(User).where(User.user_id.in_(roles)).order_by(User.email))
    return [_out(u, roles[u.user_id]) for u in users.scalars()]


async def _set_roles(
    session: AsyncSession, ctx: CompanyContext, user_id: uuid.UUID, roles: list[RoleName]
) -> None:
    await session.execute(
        delete(UserRole).where(UserRole.company_id == ctx.company_id, UserRole.user_id == user_id)
    )
    for role in roles:
        session.add(
            UserRole(
                user_id=user_id,
                company_id=ctx.company_id,
                role_id=await role_id(session, role),
            )
        )
    await session.flush()


async def _lock_company(session: AsyncSession, ctx: CompanyContext) -> None:
    """Serialise role changes per company, so two Owners removing each other concurrently
    cannot leave it with none."""
    await session.execute(
        select(Company.company_id).where(Company.company_id == ctx.company_id).with_for_update()
    )


async def add_user(session: AsyncSession, ctx: CompanyContext, data: UserCreate) -> CompanyUserOut:
    await _lock_company(session, ctx)
    user = (
        await session.execute(select(User).where(func.lower(User.email) == data.email))
    ).scalar_one_or_none()
    action = "USER_ATTACHED"
    if user is None:
        action = "USER_CREATED"
        user = User(email=data.email, name=data.name, password_hash=hash_password(data.password))
        session.add(user)
        await session.flush()
    elif await _roles_in(session, ctx.company_id, user.user_id):
        raise AppError(
            ErrorCode.CONFLICT, "User already belongs to this company; change their roles", 409
        )
    await _set_roles(session, ctx, user.user_id, data.roles)
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action=action,
        entity_type="user",
        entity_id=str(user.user_id),
        before={"roles": []},
        after={"roles": data.roles},
    )
    await session.commit()
    return _out(user, list(data.roles))


async def update_roles(
    session: AsyncSession, ctx: CompanyContext, user_id: uuid.UUID, data: RolesUpdate
) -> CompanyUserOut:
    await _lock_company(session, ctx)
    all_roles = await _roles_in(session, ctx.company_id)
    before = all_roles.get(user_id)
    user = await session.get(User, user_id)
    if before is None or user is None:  # never reveal users of other companies
        raise AppError(ErrorCode.NOT_FOUND, "User not found in this company", 404)
    other_owners = [
        uid for uid, roles in all_roles.items() if uid != user_id and RoleName.OWNER in roles
    ]
    if RoleName.OWNER in before and RoleName.OWNER not in data.roles and not other_owners:
        raise AppError(ErrorCode.CONFLICT, "A company must keep at least one Owner", 409)
    await _set_roles(session, ctx, user_id, data.roles)
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="ROLES_CHANGED",
        entity_type="user",
        entity_id=str(user_id),
        before={"roles": before},
        after={"roles": data.roles},
    )
    await session.commit()
    return _out(user, list(data.roles))
