"""Compare Tally's own figures with the synced data (SRS 9, REC-1.1-1.3, D-008, D-048).

- Tally side: only `reconciliation_tally_values`, what this RECONCILIATION run uploaded.
- Local side: only the synced rows, through `app.analytics.query` (and `stock_snapshots`).
Neither is computed from the other (SRS 9.1). What each figure means, on both sides, is in
docs/reconciliation-basis.md.
"""

import dataclasses
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import blocks, query
from app.analytics.classification import Classes
from app.analytics.context import AnalyticsFilter, MetricContext, load
from app.core import periods
from app.core.gates import gate_passed
from app.core.permissions import CompanyContext
from app.models.balances import StockSnapshot
from app.models.company import Company
from app.models.enums import (
    BaseVoucherType,
    MasterStatus,
    ReconOverall,
    SyncRunStatus,
    TallyValueKind,
)
from app.models.masters import Group, Ledger, StockItem, VoucherType
from app.models.sync import ReconciliationResult, ReconciliationRun, SyncRun
from app.models.sync import ReconciliationTallyValue as TV
from app.reconciliation.tolerance import Comparison, evaluate
from app.services.settings import get_setting
from tally_contract.log import get_logger

log = get_logger(__name__)

# The Tally facts these figures rest on (docs/reconciliation-basis.md, "Gates").
GATES = ("G18", "G19", "G21", "G23", "G36", "G37")
SYSTEM = uuid.UUID(int=0)  # the job acts for no user; only the company id is used


@dataclass(frozen=True)
class Total:
    metric: str  # reconciliation_results.metric
    local: str  # the analytics query summed on the local side
    side: str  # the Tally column summed: "debit" or "credit"
    base: BaseVoucherType
    ledgers: Callable[[Classes], frozenset[uuid.UUID]]


TOTALS = (
    Total("SALES_CREDITS", "sales", "credit", BaseVoucherType.SALES, lambda c: c.sales),
    Total("PURCHASE_DEBITS", "purchases", "debit", BaseVoucherType.PURCHASE, lambda c: c.purchase),
    Total("RECEIPTS", "recon_receipts", "debit", BaseVoucherType.RECEIPT, lambda c: c.cash_bank),
    Total("PAYMENTS", "recon_payments", "credit", BaseVoucherType.PAYMENT, lambda c: c.cash_bank),
)


@dataclass
class Outcome:
    run: SyncRun
    now: datetime
    results: list[ReconciliationResult] = dataclasses.field(default_factory=list)
    not_compared: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def compare(
        self,
        metric: str,
        start: date,
        end: date,
        tally: Decimal,
        local: Decimal,
        tolerances: tuple[Decimal, Decimal],
        entity_id: uuid.UUID | None = None,
    ) -> None:
        c: Comparison = evaluate(tally, local, *tolerances)
        self.results.append(
            ReconciliationResult(
                company_id=self.run.company_id,
                sync_run_id=self.run.sync_run_id,
                run_at=self.now,
                metric=metric,
                entity_id=entity_id,
                period_start=start,
                period_end=end,
                tally_value=tally,
                local_value=local,
                absolute_difference=c.absolute_difference,
                percentage_difference=c.percentage_difference,
                result=c.result,
            )
        )

    def skip(self, metric: str, guid: str, name: str | None, reason: str, fails: bool) -> None:
        self.not_compared.append(
            {"metric": metric, "entity_guid": guid, "name": name, "reason": reason, "fails": fails}
        )


async def _tolerances(
    session: AsyncSession, company_id: uuid.UUID, kind: str
) -> tuple[Decimal, Decimal]:
    return (
        await get_setting(session, company_id, f"reconciliation.{kind}_absolute_tolerance"),
        await get_setting(session, company_id, f"reconciliation.{kind}_percentage_tolerance"),
    )


def _values(run: SyncRun, kind: TallyValueKind) -> Any:
    return (TV.company_id == run.company_id, TV.sync_run_id == run.sync_run_id, TV.kind == kind)


async def _totals(
    session: AsyncSession, out: Outcome, ctx: MetricContext, as_of: date, fy_start: date
) -> None:
    """SALES_CREDITS, PURCHASE_DEBITS, RECEIPTS, PAYMENTS for every period. Tally's sums per
    (ledger, voucher type) are classified exactly as the synced entries are (D-048 #4)."""
    run = out.run
    money = await _tolerances(session, run.company_id, "money")
    ledger_match = and_(Ledger.company_id == TV.company_id, Ledger.tally_guid == TV.entity_guid)
    type_match = and_(
        VoucherType.company_id == TV.company_id, VoucherType.tally_guid == TV.voucher_type_guid
    )
    unmatched = await session.execute(
        select(TV.entity_guid, TV.name, TV.voucher_type_guid)
        .where(
            *_values(run, TallyValueKind.TOTAL),
            or_(TV.debit != 0, TV.credit != 0),
            or_(~exists().where(ledger_match), ~exists().where(type_match)),
        )
        .distinct()
    )
    for guid, name, type_guid in unmatched.tuples():
        out.skip("TOTALS", guid, name, f"ledger or voucher type ({type_guid}) not synced", True)
    # ponytail: one statement per metric and period (~56 a run); a monthly series per metric
    # is the upgrade if the daily job ever gets slow at SRS 17.2 size.
    for p in periods.reconciliation_periods(as_of, fy_start):
        local_ctx = dataclasses.replace(  # raw: no return linking, no tax ledgers (D-008)
            ctx,
            filter=AnalyticsFilter(p.start, p.end),
            returns_linkable=False,
            taxable_value_mode=True,
        )
        for t in TOTALS:
            column = TV.debit if t.side == "debit" else TV.credit
            tally = await session.scalar(
                select(func.coalesce(func.sum(column), 0))
                .select_from(TV)
                .join(Ledger, ledger_match)
                .join(VoucherType, type_match)
                .where(
                    *_values(run, TallyValueKind.TOTAL),
                    TV.period_start == p.start,
                    TV.period_end == p.end,
                    blocks.in_class(t.ledgers(ctx.classes)),
                    VoucherType.base_voucher_type == t.base,
                )
            )
            local = await query.total(session, local_ctx, t.local)
            out.compare(t.metric, p.start, p.end, Decimal(tally or 0), local or Decimal(0), money)


async def _ledger_balances(
    session: AsyncSession, out: Outcome, ctx: MetricContext, as_of: date, fy_start: date
) -> bool:
    """ACC-9.5, TEST-4.2: every ledger's Phase 8 balance against Tally's own closing balance.
    Returns whether Tally's balances arrived at all."""
    run = out.run
    money = await _tolerances(session, run.company_id, "money")
    tally = (
        await session.execute(
            select(TV.entity_guid, TV.name, TV.value).where(
                *_values(run, TallyValueKind.LEDGER_CLOSING)
            )
        )
    ).all()
    if not tally:
        return False
    local_ctx = dataclasses.replace(ctx, filter=AnalyticsFilter(fy_start, as_of))
    rows = await query.breakdown(session, local_ctx, "ledger_balances", "ledger_id", "ledger_name")
    local = {ledger_id: amount for ledger_id, _, amount in rows}
    ledgers = {
        guid: (ledger_id, name, status, nature)
        for guid, ledger_id, name, status, nature in (
            await session.execute(
                select(
                    Ledger.tally_guid, Ledger.ledger_id, Ledger.name, Ledger.status, Group.nature
                )
                .outerjoin(
                    Group,
                    and_(
                        Group.company_id == Ledger.company_id,
                        Group.group_id == Ledger.classification_group_id,
                    ),
                )
                .where(Ledger.company_id == run.company_id)
            )
        ).tuples()
    }
    metric = "LEDGER_BALANCE"
    for guid, name, value in tally:
        if guid not in ledgers:
            out.skip(metric, guid, name, "in Tally, not in the synced ledgers", True)
            continue
        ledger_id, local_name, _, nature = ledgers[guid]
        if nature is None:  # ACC-7.4: no anchor, so no nature and no balance
            out.skip(metric, guid, local_name, "unresolved group chain (Data Quality)", False)
            continue
        amount = local.get(ledger_id, Decimal(0))  # an income/expense ledger with no movement
        if amount is None:  # ACC-9.6
            out.skip(metric, guid, local_name, "opening balance unavailable (Data Quality)", False)
            continue
        out.compare(metric, fy_start, as_of, Decimal(value or 0), amount, money, ledger_id)
    reported = {guid for guid, _, _ in tally}
    for guid, (_, name, status, _) in ledgers.items():
        if status == MasterStatus.ACTIVE and guid not in reported:
            out.skip(metric, guid, name, "not in Tally's closing balances", True)
    return True


async def _stock(session: AsyncSession, out: Outcome, as_of: date) -> None:
    """D-048 #3: Tally's closing quantity, read moments after this run stored its snapshot."""
    run = out.run
    quantity = await _tolerances(session, run.company_id, "quantity")
    items = {
        guid: (item_id, name)
        for guid, item_id, name in (
            await session.execute(
                select(StockItem.tally_guid, StockItem.stock_item_id, StockItem.name).where(
                    StockItem.company_id == run.company_id
                )
            )
        ).tuples()
    }
    stored = {
        item_id: (qty, unit)
        for item_id, qty, unit in (
            await session.execute(
                select(
                    StockSnapshot.stock_item_id, StockSnapshot.closing_quantity, StockSnapshot.unit
                ).where(
                    StockSnapshot.company_id == run.company_id,
                    StockSnapshot.sync_run_id == run.sync_run_id,
                    StockSnapshot.as_of_date == as_of,
                )
            )
        ).tuples()
    }
    tally = await session.execute(
        select(TV.entity_guid, TV.value, TV.unit).where(*_values(run, TallyValueKind.STOCK_CLOSING))
    )
    metric = "STOCK_QTY"
    for guid, value, unit in tally.tuples():
        if guid not in items:
            out.skip(metric, guid, None, "in Tally, not in the synced stock items", True)
            continue
        item_id, name = items[guid]
        if item_id not in stored:
            out.skip(metric, guid, name, "no snapshot stored by this run", True)
            continue
        qty, stored_unit = stored[item_id]
        if stored_unit != unit:  # quantities in different units are never compared (D-046 #4)
            out.skip(metric, guid, name, f"units differ: Tally {unit}, stored {stored_unit}", True)
            continue
        out.compare(metric, as_of, as_of, Decimal(value or 0), qty, quantity, item_id)


async def reconcile_run(session: AsyncSession, run: SyncRun, now: datetime) -> ReconciliationRun:
    """Compare one finished RECONCILIATION run and record every comparison (REC-1.3)."""
    company = await session.get(Company, run.company_id)
    assert company is not None
    as_of = periods.to_local_date(run.started_at, company.company_timezone)  # the plan's as_of
    fy_start = periods.financial_year_of(as_of, company.financial_year_start).start
    ctx = await load(
        session,
        CompanyContext(run.company_id, SYSTEM, frozenset()),
        AnalyticsFilter(fy_start, as_of),
    )
    out = Outcome(run, now)
    await _totals(session, out, ctx, as_of, fy_start)
    balances_arrived = await _ledger_balances(session, out, ctx, as_of, fy_start)
    await _stock(session, out, as_of)
    failed = sum(r.result == "FAIL" for r in out.results) + sum(
        n["fails"] for n in out.not_compared
    )
    overall = (
        ReconOverall.FAIL
        if failed
        else ReconOverall.INCOMPLETE
        if run.status == SyncRunStatus.PARTIAL or not balances_arrived
        else ReconOverall.PASS
    )
    summary = ReconciliationRun(
        sync_run_id=run.sync_run_id,
        company_id=run.company_id,
        run_at=now,
        as_of=as_of,
        overall=overall,
        compared=len(out.results),
        failed=failed,
        not_compared=out.not_compared,
        unverified_gates=[g for g in GATES if not gate_passed(g)],
    )
    session.add_all([*out.results, summary])
    await session.flush()
    log.info(
        "reconciliation_compared",
        sync_run_id=str(run.sync_run_id),
        overall=overall.value,
        compared=len(out.results),
        failed=failed,
    )
    return summary
