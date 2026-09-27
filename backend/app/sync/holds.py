"""Failed records hold the watermark back (D-039 #7).

A record that fails is written to sync_errors with `watermark_hold`: the highest the watermark
may go while that record keeps failing (its ALTERID - 1, or the pre-batch watermark when its
ALTERID is unknown). Within a run the lowest hold caps every watermark move for that collection;
the next run starts below the failure, so it retries it. A permanent failure therefore never
lets the watermark pass it.
"""

import uuid

from sqlalchemy import Integer, String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CollectionType
from app.models.sync import SyncError, SyncWatermark


async def run_cap(
    session: AsyncSession, sync_run_id: uuid.UUID, collection: CollectionType
) -> int | None:
    """The lowest hold this run has recorded for the collection, if any."""
    cap = await session.scalar(
        select(func.min(SyncError.watermark_hold)).where(
            SyncError.sync_run_id == sync_run_id,
            SyncError.entity_type == collection.value,
            SyncError.watermark_hold.is_not(None),
        )
    )
    return None if cap is None else int(cap)


def capped(chunk_max: int, cap: int | None) -> int:
    return chunk_max if cap is None else min(chunk_max, cap)


async def held_back(session: AsyncSession, company_id: uuid.UUID) -> dict[str, int]:
    """Data Quality: "sync held back by N failing records", per collection. Counts the failing
    records of each collection's latest failing run whose hold still stops the watermark."""
    latest = (
        select(SyncError.entity_type, func.max(SyncError.created_at).label("at"))
        .where(SyncError.company_id == company_id, SyncError.watermark_hold.is_not(None))
        .group_by(SyncError.entity_type)
        .subquery()
    )
    latest_run = (
        select(SyncError.entity_type, SyncError.sync_run_id)
        .join(
            latest,
            (latest.c.entity_type == SyncError.entity_type) & (latest.c.at == SyncError.created_at),
        )
        .where(SyncError.company_id == company_id)
        .distinct()
        .subquery()
    )
    rows = await session.execute(
        select(
            SyncError.entity_type,
            func.count(
                func.distinct(func.coalesce(SyncError.tally_guid, cast(SyncError.id, String)))
            ),
        )
        .join(
            latest_run,
            (latest_run.c.sync_run_id == SyncError.sync_run_id)
            & (latest_run.c.entity_type == SyncError.entity_type),
        )
        .join(
            SyncWatermark,
            (SyncWatermark.company_id == SyncError.company_id)
            & (SyncWatermark.collection_type == SyncError.entity_type),
        )
        .where(
            SyncError.company_id == company_id,
            SyncError.watermark_hold.is_not(None),
            SyncError.watermark_hold >= cast(SyncWatermark.last_alter_id, Integer),
        )
        .group_by(SyncError.entity_type)
    )
    return {entity: int(count) for entity, count in rows.tuples()}
