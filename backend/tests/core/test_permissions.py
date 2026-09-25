"""P2.3: the permission matrix equals SRS 14.1 (read row by row from the SRS table)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_PERMISSIONS, CompanyContext, Permission, scoped
from app.models.enums import Nature, RoleName
from app.models.masters import Group
from tests.factories import make_company, make_group

Y, N = True, False
# Permission: (Owner, Accountant, Admin) - SRS 14.1, row for row.
SRS_14_1 = {
    Permission.VIEW_FINANCIALS: (Y, Y, Y),
    Permission.RUN_SYNC: (Y, Y, Y),
    Permission.MANAGE_SCHEDULES: (Y, N, Y),
    Permission.EXPORT: (Y, Y, Y),
    Permission.VIEW_RECON_AND_DQ: (Y, Y, Y),
    Permission.VIEW_LOGS: (Y, N, Y),
    Permission.REVIEW_ANOMALIES: (Y, Y, N),
    Permission.MANAGE_SETTINGS: (Y, N, Y),
    Permission.MANAGE_AGENTS: (Y, N, Y),
    Permission.MANAGE_CUSTOM_FIELDS: (Y, N, Y),
    Permission.MANAGE_USERS: (Y, N, N),
}
ROLES = (RoleName.OWNER, RoleName.ACCOUNTANT, RoleName.ADMIN)


def test_matrix_covers_every_permission_and_role() -> None:
    assert set(SRS_14_1) == set(Permission)
    assert set(ROLE_PERMISSIONS) == set(RoleName)


@pytest.mark.parametrize("permission", list(Permission))
def test_matrix_equals_srs_14_1(permission: Permission) -> None:
    actual = tuple(permission in ROLE_PERMISSIONS[role] for role in ROLES)
    assert actual == SRS_14_1[permission]


async def test_scoped_filters_to_the_context_company(session: AsyncSession) -> None:
    a, b = await make_company(session, name="A"), await make_company(session, name="B")
    await make_group(session, a, "Mine", None, Nature.ASSET)
    await make_group(session, b, "Theirs", None, Nature.ASSET)
    ctx = CompanyContext(a.company_id, a.company_id, frozenset())
    names = (await session.execute(scoped(select(Group.name), Group, ctx))).scalars().all()
    assert names == ["Mine"]
