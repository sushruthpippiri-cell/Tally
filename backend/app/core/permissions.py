"""SRS 14.1 permissions, the `require()` dependency and the company context (RBAC-1.x, SEC-1.7).

Every company-scoped route takes `ctx: CompanyContext = Depends(require(Permission.X))`, and
`ctx.company_id` is the only company id its queries may use. tests/api/test_route_access.py
finds every route automatically and checks this.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import current_user
from app.models.company import Role, User, UserRole
from app.models.enums import RoleName
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)


class Permission(StrEnum):
    VIEW_FINANCIALS = "VIEW_FINANCIALS"
    RUN_SYNC = "RUN_SYNC"
    MANAGE_SCHEDULES = "MANAGE_SCHEDULES"
    EXPORT = "EXPORT"
    VIEW_RECON_AND_DQ = "VIEW_RECON_AND_DQ"
    VIEW_LOGS = "VIEW_LOGS"
    REVIEW_ANOMALIES = "REVIEW_ANOMALIES"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"  # feature flags and settings
    MANAGE_AGENTS = "MANAGE_AGENTS"  # register/rotate/revoke, Tally connection settings
    MANAGE_CUSTOM_FIELDS = "MANAGE_CUSTOM_FIELDS"
    MANAGE_USERS = "MANAGE_USERS"


P = Permission
_EVERYONE = {P.VIEW_FINANCIALS, P.RUN_SYNC, P.EXPORT, P.VIEW_RECON_AND_DQ}
_OWNER_AND_ADMIN = {P.MANAGE_SCHEDULES, P.VIEW_LOGS, P.MANAGE_SETTINGS, P.MANAGE_AGENTS}

# SRS 14.1, exactly.
ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.OWNER: frozenset(Permission),
    RoleName.ACCOUNTANT: frozenset(_EVERYONE | {P.REVIEW_ANOMALIES}),
    RoleName.ADMIN: frozenset(_EVERYONE | _OWNER_AND_ADMIN | {P.MANAGE_CUSTOM_FIELDS}),
}

FORBIDDEN_MESSAGE = "Not permitted for this company"


@dataclass(frozen=True)
class CompanyContext:
    company_id: uuid.UUID
    user_id: uuid.UUID
    roles: frozenset[RoleName]


@dataclass(frozen=True)
class Require:
    """A dependency object (not a closure) so the route test can read `.permission`."""

    permission: Permission

    async def __call__(
        self,
        company_id: uuid.UUID,
        user: User = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> CompanyContext:
        names = await session.execute(
            select(Role.role_name)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user.user_id, UserRole.company_id == company_id)
        )
        roles = frozenset(RoleName(n) for n in names.scalars())
        # Same answer for "no role here" and "no such company" (AC-60).
        if not any(self.permission in ROLE_PERMISSIONS[r] for r in roles):
            log.info(
                "permission_denied",
                user_id=str(user.user_id),
                company_id=str(company_id),
                permission=self.permission.value,
            )
            raise AppError(ErrorCode.FORBIDDEN, FORBIDDEN_MESSAGE, 403)
        return CompanyContext(company_id, user.user_id, roles)


def require(permission: Permission) -> Require:
    return Require(permission)


def scoped[S](stmt: S, model: Any, ctx: CompanyContext) -> S:
    """Add `model.company_id == ctx.company_id` (SEC-1.7)."""
    return stmt.where(model.company_id == ctx.company_id)  # type: ignore[attr-defined, no-any-return]
