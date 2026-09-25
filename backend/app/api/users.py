import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import CompanyContext, Permission, require
from app.schemas.users import CompanyUserOut, RolesUpdate, UserCreate
from app.services import users

router = APIRouter(prefix="/companies/{company_id}/users", tags=["users"])
MANAGE_USERS = Depends(require(Permission.MANAGE_USERS))


@router.get("")
async def list_users(
    ctx: CompanyContext = MANAGE_USERS, session: AsyncSession = Depends(get_session)
) -> list[CompanyUserOut]:
    return await users.list_users(session, ctx)


@router.post("", status_code=201)
async def add_user(
    body: UserCreate,
    ctx: CompanyContext = MANAGE_USERS,
    session: AsyncSession = Depends(get_session),
) -> CompanyUserOut:
    return await users.add_user(session, ctx, body)


@router.put("/{user_id}")
async def update_roles(
    user_id: uuid.UUID,
    body: RolesUpdate,
    ctx: CompanyContext = MANAGE_USERS,
    session: AsyncSession = Depends(get_session),
) -> CompanyUserOut:
    return await users.update_roles(session, ctx, user_id, body)
