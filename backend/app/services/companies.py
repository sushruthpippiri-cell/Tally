"""Companies (D-006). The creator becomes OWNER; a company is inactive until an Agent registers."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.permissions import CompanyContext
from app.models.company import Company, Role, User, UserRole
from app.models.enums import RoleName
from app.schemas.companies import CompanyCreate, CompanyOut, CompanyUpdate


def _out(company: Company, roles: frozenset[RoleName] | list[RoleName]) -> CompanyOut:
    return CompanyOut(
        company_id=company.company_id,
        name=company.name,
        financial_year_start=company.financial_year_start,
        company_timezone=company.company_timezone,
        is_active=company.is_active,
        tally_guid=company.tally_guid,
        my_roles=sorted(roles),
    )


def _fields(company: Company) -> dict[str, Any]:
    return {
        "name": company.name,
        "financial_year_start": company.financial_year_start.isoformat(),
        "company_timezone": company.company_timezone,
    }


async def role_id(session: AsyncSession, role: RoleName) -> int:
    return (await session.execute(select(Role.role_id).where(Role.role_name == role))).scalar_one()


async def create_company(session: AsyncSession, user: User, data: CompanyCreate) -> CompanyOut:
    company = Company(**data.model_dump(), is_active=False)
    session.add(company)
    await session.flush()
    session.add(
        UserRole(
            user_id=user.user_id,
            company_id=company.company_id,
            role_id=await role_id(session, RoleName.OWNER),
        )
    )
    await audit.record(
        session,
        company_id=company.company_id,
        user_id=user.user_id,
        action="COMPANY_CREATED",
        entity_type="company",
        entity_id=str(company.company_id),
        after=_fields(company),
    )
    await session.commit()
    return _out(company, [RoleName.OWNER])


async def list_companies(session: AsyncSession, user_id: uuid.UUID) -> list[CompanyOut]:
    rows = await session.execute(
        select(Company, Role.role_name)
        .join(UserRole, UserRole.company_id == Company.company_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(Company.name, Company.company_id)
    )
    by_id: dict[uuid.UUID, tuple[Company, list[RoleName]]] = {}
    for company, role in rows.tuples():
        by_id.setdefault(company.company_id, (company, []))[1].append(RoleName(role))
    return [_out(c, roles) for c, roles in by_id.values()]


async def _load(session: AsyncSession, ctx: CompanyContext) -> Company:
    company = await session.get(Company, ctx.company_id)
    assert company is not None  # ctx exists only for a company the user holds a role in
    return company


async def get_company(session: AsyncSession, ctx: CompanyContext) -> CompanyOut:
    return _out(await _load(session, ctx), ctx.roles)


async def update_company(
    session: AsyncSession, ctx: CompanyContext, data: CompanyUpdate
) -> CompanyOut:
    company = await _load(session, ctx)
    before = _fields(company)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(company, key, value)
    changed_before, changed_after = audit.diff(before, _fields(company))
    if changed_after:
        await audit.record(
            session,
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            action="COMPANY_UPDATED",
            entity_type="company",
            entity_id=str(ctx.company_id),
            before=changed_before,
            after=changed_after,
        )
    await session.commit()
    return _out(company, ctx.roles)
