"""The sync lease (SRS 6.3, SYNC-4.x): one writer per (company, collection).

Each call is one conditional UPDATE, so a lease can be held by one Agent only. Leases share the
command's timer: TTL = agent.command_lease_seconds, renewed by every progress call (D-039 #3).
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.models.agents import Agent
from app.models.enums import CollectionType
from app.models.sync import SyncWatermark
from app.services.settings import get_setting
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger

log = get_logger(__name__)


async def ttl(session: AsyncSession, company_id: uuid.UUID) -> timedelta:
    return timedelta(seconds=await get_setting(session, company_id, "agent.command_lease_seconds"))


def _mine(agent: AgentContext, collection: CollectionType):  # type: ignore[no-untyped-def]
    return and_(
        SyncWatermark.company_id == agent.company_id,
        SyncWatermark.collection_type == collection,
        SyncWatermark.locked_by_agent_id == agent.agent_id,
    )


async def acquire(
    session: AsyncSession, agent: AgentContext, collection: CollectionType, now: datetime
) -> SyncWatermark:
    """SYNC-4.1: compare-and-set; SYNC-4.2: another live holder -> SYNC_LOCKED; SYNC-4.3: an
    expired lease is simply taken. Does not commit."""
    await session.execute(
        insert(SyncWatermark)
        .values(company_id=agent.company_id, collection_type=collection)
        .on_conflict_do_nothing()
    )
    until = now + await ttl(session, agent.company_id)
    row = (
        await session.execute(
            update(SyncWatermark)
            .where(
                SyncWatermark.company_id == agent.company_id,
                SyncWatermark.collection_type == collection,
                (SyncWatermark.locked_by_agent_id.is_(None))
                | (SyncWatermark.lock_expires_at <= now)
                | (SyncWatermark.locked_by_agent_id == agent.agent_id),
            )
            .values(locked_by_agent_id=agent.agent_id, lock_acquired_at=now, lock_expires_at=until)
            .returning(SyncWatermark)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    if row is None:
        holder = (
            await session.execute(
                select(Agent.agent_name, SyncWatermark.lock_expires_at)
                .join(Agent, Agent.agent_id == SyncWatermark.locked_by_agent_id)
                .where(
                    SyncWatermark.company_id == agent.company_id,
                    SyncWatermark.collection_type == collection,
                )
            )
        ).one_or_none()
        name, expires = holder if holder else ("another Agent", None)
        log.info("sync_lease_refused", collection=collection.value, holder=name)
        raise AppError(
            ErrorCode.SYNC_LOCKED,
            f"{collection.value} is being synced by Agent '{name}'"
            + (f" until {expires.isoformat()}" if expires else ""),
            409,
            {"holder": name, "collection_type": collection.value},
        )
    return row


async def renew_all(session: AsyncSession, agent: AgentContext, now: datetime) -> int:
    """Extend every LIVE lease this Agent holds; an expired one must be re-acquired."""
    until = now + await ttl(session, agent.company_id)
    result = await session.execute(
        update(SyncWatermark)
        .where(
            SyncWatermark.company_id == agent.company_id,
            SyncWatermark.locked_by_agent_id == agent.agent_id,
            SyncWatermark.lock_expires_at > now,
        )
        .values(lock_expires_at=until)
        .returning(SyncWatermark.collection_type)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def release_all(session: AsyncSession, company_id: uuid.UUID, agent_id: uuid.UUID) -> int:
    result = await session.execute(
        update(SyncWatermark)
        .where(SyncWatermark.company_id == company_id, SyncWatermark.locked_by_agent_id == agent_id)
        .values(locked_by_agent_id=None, lock_acquired_at=None, lock_expires_at=None)
        .returning(SyncWatermark.collection_type)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def lock_held(
    session: AsyncSession, agent: AgentContext, collection: CollectionType, now: datetime
) -> SyncWatermark | None:
    """The chunk guard (D-039 #1): the watermark row, locked FOR UPDATE, if and only if this
    Agent holds a live lease on it."""
    return (
        await session.execute(
            select(SyncWatermark)
            .where(_mine(agent, collection), SyncWatermark.lock_expires_at > now)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def not_held(collection: CollectionType) -> AppError:
    return AppError(
        ErrorCode.SYNC_LOCKED,
        f"This Agent does not hold a live lease on {collection.value}; acquire it first",
        409,
        {"collection_type": collection.value},
    )


async def release(
    session: AsyncSession,
    agent: AgentContext,
    collection: CollectionType,
    now: datetime,
    advance_to: int | None,
) -> int:
    """Release this Agent's lease; with `advance_to`, first move the watermark there (D-039 #2),
    only while the lease is still live (a lease taken over is not this Agent's to move)."""
    row = await lock_held(session, agent, collection, now)
    if advance_to is not None and row is not None:
        row.last_alter_id = max(row.last_alter_id, advance_to)
        row.last_successful_sync_at = now
        row.status = "OK"
    await session.execute(
        update(SyncWatermark)
        .where(_mine(agent, collection))
        .values(locked_by_agent_id=None, lock_acquired_at=None, lock_expires_at=None)
        .execution_options(synchronize_session=False)
    )
    last = await session.scalar(
        select(SyncWatermark.last_alter_id).where(
            SyncWatermark.company_id == agent.company_id,
            SyncWatermark.collection_type == collection,
        )
    )
    return int(last or 0)
