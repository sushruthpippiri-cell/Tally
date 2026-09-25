"""Credential rotation on real, committing connections (SEC-2.1, SEC-2.3)."""

import asyncio
import uuid

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.agent_credentials import current_agent
from app.core.errors import AppError
from app.core.permissions import CompanyContext
from app.models.enums import RoleName
from app.services.agent_admin import revoke, revoke_uncommitted, rotate, rotate_uncommitted
from tests.factories import make_company, make_registered_agent, make_user

Factory = async_sessionmaker[AsyncSession]


async def _setup(committed: Factory) -> tuple[CompanyContext, str, str]:
    async with committed() as s:
        company = await make_company(s)
        owner = await make_user(s, company, RoleName.OWNER)
        agent, credential = await make_registered_agent(s, company)
        await s.commit()
    ctx = CompanyContext(company.company_id, owner.user_id, frozenset({RoleName.OWNER}))
    return ctx, str(agent.agent_id), credential


async def _auth(committed: Factory, credential: str) -> str:
    """What an Agent request with this credential gets, on its own connection."""
    async with committed() as s:
        try:
            await current_agent(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=credential), s
            )
        except AppError as exc:
            return exc.code.value
        return "OK"


@pytest.mark.req("SEC-2.1")
async def test_rotation_switches_credentials_in_one_instant(committed: Factory) -> None:
    """SEC-2.1: while the rotation is uncommitted only the old credential works; the moment it
    commits only the new one does. There is no state in which both work."""
    ctx, agent_id, old = await _setup(committed)
    async with committed() as rotating:
        new = (await rotate_uncommitted(rotating, ctx, uuid.UUID(agent_id))).credential
        assert (await _auth(committed, old), await _auth(committed, new)) == (
            "OK",
            "CREDENTIAL_INVALID",
        )
        await rotating.commit()
    assert (await _auth(committed, old), await _auth(committed, new)) == (
        "CREDENTIAL_INVALID",
        "OK",
    )


async def test_rotation_blocked_behind_a_revocation_is_refused(committed: Factory) -> None:
    ctx, agent_id, old = await _setup(committed)
    async with committed() as revoking:
        await revoke_uncommitted(revoking, ctx, uuid.UUID(agent_id))
        rotation = asyncio.create_task(_rotate(committed, ctx, agent_id))
        await asyncio.sleep(0.3)
        assert not rotation.done(), "rotation must wait for the revocation's row lock"
        await revoking.commit()
    assert await rotation == "AGENT_REVOKED"
    assert await _auth(committed, old) == "AGENT_REVOKED"


async def test_revocation_after_a_rotation_leaves_no_working_credential(committed: Factory) -> None:
    ctx, agent_id, old = await _setup(committed)
    async with committed() as rotating:
        new = (await rotate_uncommitted(rotating, ctx, uuid.UUID(agent_id))).credential
        revocation = asyncio.create_task(_revoke(committed, ctx, agent_id))
        await asyncio.sleep(0.3)
        assert not revocation.done()
        await rotating.commit()
    assert await revocation == "REVOKED"
    assert await _auth(committed, new) == "AGENT_REVOKED"  # correct secret, but revoked
    assert await _auth(committed, old) == "CREDENTIAL_INVALID"


async def test_two_concurrent_rotations_leave_exactly_one_working_credential(
    committed: Factory,
) -> None:
    ctx, agent_id, old = await _setup(committed)
    first, second = await asyncio.gather(
        _rotate(committed, ctx, agent_id, want_credential=True),
        _rotate(committed, ctx, agent_id, want_credential=True),
    )
    results = [await _auth(committed, c) for c in (old, first, second)]
    assert results[0] == "CREDENTIAL_INVALID"
    assert sorted(results[1:]) == ["CREDENTIAL_INVALID", "OK"]


async def _rotate(
    committed: Factory, ctx: CompanyContext, agent_id: str, want_credential: bool = False
) -> str:
    async with committed() as s:
        try:
            rotated = await rotate(s, ctx, uuid.UUID(agent_id))
        except AppError as exc:
            return exc.code.value
        return rotated.credential if want_credential else "ROTATED"


async def _revoke(committed: Factory, ctx: CompanyContext, agent_id: str) -> str:
    async with committed() as s:
        try:
            await revoke(s, ctx, uuid.UUID(agent_id))
        except AppError as exc:
            return exc.code.value
        return "REVOKED"
