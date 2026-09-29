"""Reconciliation results for the dashboard (REC-1.2, FR-4.1, AGT-6.4) and on-demand runs
(REC-1.4). The comparisons themselves are made by the job (app/jobs/reconciliation.py)."""

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.permissions import CompanyContext, scoped
from app.models.enums import SyncMode
from app.models.masters import Ledger, StockItem
from app.models.sync import ReconciliationResult, ReconciliationRun
from app.schemas.commands import CommandStatusOut, SyncRequest
from app.schemas.reconciliation import (
    NotCompared,
    ReconciliationOut,
    ReconciliationRow,
    ReconciliationStatus,
    RunOverview,
)
from app.services import commands
from tally_contract.errors import ErrorCode

HISTORY = 30
METRIC_ORDER = ["SALES_CREDITS", "PURCHASE_DEBITS", "RECEIPTS", "PAYMENTS", "LEDGER_BALANCE"]


async def run(
    session: AsyncSession, ctx: CompanyContext, agent_id: uuid.UUID | None
) -> CommandStatusOut:
    """REC-1.4 on demand: a RECONCILIATION command, routed like Sync Now."""
    return await commands.create_command(
        session, ctx, SyncRequest(sync_mode=SyncMode.RECONCILIATION), agent_id
    )


def _overview(r: ReconciliationRun) -> RunOverview:
    return RunOverview(
        sync_run_id=r.sync_run_id,
        run_at=r.run_at,
        as_of=r.as_of,
        overall=r.overall,
        compared=r.compared,
        failed=r.failed,
    )


async def latest(session: AsyncSession, company_id: uuid.UUID) -> ReconciliationRun | None:
    return (
        await session.execute(
            select(ReconciliationRun)
            .where(ReconciliationRun.company_id == company_id)
            .order_by(ReconciliationRun.run_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def status(session: AsyncSession, company_id: uuid.UUID) -> ReconciliationStatus | None:
    found = await latest(session, company_id)
    if found is None:
        return None
    return ReconciliationStatus(
        sync_run_id=found.sync_run_id,
        run_at=found.run_at,
        overall=found.overall,
    )


async def view(
    session: AsyncSession,
    ctx: CompanyContext,
    run_id: uuid.UUID | None,
    only_failures: bool,
    offset: int,
    limit: int,
) -> ReconciliationOut:
    history = [
        _overview(r)
        for r in (
            await session.execute(
                scoped(select(ReconciliationRun), ReconciliationRun, ctx)
                .order_by(ReconciliationRun.run_at.desc())
                .limit(HISTORY)
            )
        ).scalars()
    ]
    if run_id is None:
        chosen = await latest(session, ctx.company_id)
    else:
        chosen = (
            await session.execute(
                scoped(select(ReconciliationRun), ReconciliationRun, ctx).where(
                    ReconciliationRun.sync_run_id == run_id
                )
            )
        ).scalar_one_or_none()
        if chosen is None:
            raise AppError(ErrorCode.NOT_FOUND, "Reconciliation run not found", 404)
    if chosen is None:
        return ReconciliationOut(
            run=None, rows=[], total_rows=0, not_compared=[], unverified_gates=[], history=[]
        )
    r = ReconciliationResult
    rows = scoped(select(r), r, ctx).where(r.sync_run_id == chosen.sync_run_id)
    if only_failures:
        rows = rows.where(r.result == "FAIL")
    total = await session.scalar(select(func.count()).select_from(rows.subquery()))
    name = func.coalesce(Ledger.name, StockItem.name)
    metric_rank = case({m: i for i, m in enumerate(METRIC_ORDER)}, value=r.metric, else_=99)
    page = await session.execute(
        rows.add_columns(name)
        .outerjoin(Ledger, (Ledger.company_id == r.company_id) & (Ledger.ledger_id == r.entity_id))
        .outerjoin(
            StockItem,
            (StockItem.company_id == r.company_id) & (StockItem.stock_item_id == r.entity_id),
        )
        .order_by(
            (r.result == "FAIL").desc(), metric_rank, r.period_start, r.period_end, name, r.id
        )
        .offset(offset)
        .limit(limit)
    )
    return ReconciliationOut(
        run=_overview(chosen),
        rows=[
            ReconciliationRow(
                metric=row.metric,
                entity_id=row.entity_id,
                entity_name=entity_name,
                period_start=row.period_start,
                period_end=row.period_end,
                tally_value=row.tally_value,
                local_value=row.local_value,
                absolute_difference=row.absolute_difference,
                percentage_difference=row.percentage_difference,
                result=row.result,
            )
            for row, entity_name in page.tuples()
        ],
        total_rows=int(total or 0),
        not_compared=[NotCompared(**n) for n in chosen.not_compared],
        unverified_gates=list(chosen.unverified_gates),
        history=history,
    )
