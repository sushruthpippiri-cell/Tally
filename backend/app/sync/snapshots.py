"""Stock snapshots (P5.6, FR-STK-15, D-040 #8): Tally's closing quantity per item and date,
upserted on (stock_item_id, as_of_date). No ALTERID and no watermark: a re-send replaces."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balances import StockSnapshot
from app.models.masters import StockItem
from app.sync.context import ChunkOutcome, IngestContext, RecordFailure
from tally_contract.errors import ErrorCode
from tally_contract.records import StockSnapshotRecord


async def write_snapshots(
    session: AsyncSession, ctx: IngestContext, records: list[Any]
) -> ChunkOutcome:
    outcome = ChunkOutcome()
    snapshots: list[StockSnapshotRecord] = records
    found = await session.execute(
        select(StockItem.tally_guid, StockItem.stock_item_id).where(
            StockItem.company_id == ctx.company_id,
            StockItem.tally_guid.in_({r.stock_item_guid for r in snapshots}),
        )
    )
    items = {guid: item_id for guid, item_id in found.tuples()}
    rows: dict[tuple[Any, Any], dict[str, Any]] = {}  # one row per key: the last one sent wins
    for r in snapshots:
        item = items.get(r.stock_item_guid)
        if item is None:
            outcome.failures.append(
                RecordFailure(
                    r.stock_item_guid,
                    None,
                    ErrorCode.UNKNOWN_MASTER_REFERENCE,
                    f"stock item '{r.stock_item_guid}' is not in this company's masters",
                )
            )
            continue
        rows[(item, r.as_of_date)] = {
            "company_id": ctx.company_id,
            "stock_item_id": item,
            "as_of_date": r.as_of_date,
            "closing_quantity": r.closing_quantity,
            "unit": r.unit,
            "sync_run_id": ctx.sync_run_id,
        }
    if rows:
        stmt = insert(StockSnapshot).values(list(rows.values()))
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[StockSnapshot.stock_item_id, StockSnapshot.as_of_date],
                set_={
                    "closing_quantity": stmt.excluded.closing_quantity,
                    "unit": stmt.excluded.unit,
                    "sync_run_id": stmt.excluded.sync_run_id,
                },
            )
        )
    outcome.written = len(rows)
    return outcome
