"""Expenses (ACC-1.5 as amended by D-044 #5): the net movement on Expense-class ledgers.

Σ `amount_signed` (debit +) of entries on Expense-class ledgers in ACTIVE vouchers of any
type, so a credit to an expense (a reversed provision, a refund, a reclassification) reduces
it. Rows are at cost-centre grain (D-045 #1): one per cost-centre allocation, signed like its
entry, plus the entry's unallocated remainder as "(No cost centre)"; an entry with no
allocation is one row. So the by-ledger, by-group and by-cost-centre breakdowns all total the
metric.
"""

from typing import Any

from sqlalchemy import Select, and_, case, func, literal, null, or_, select, union_all
from sqlalchemy.orm import aliased

from app.analytics import blocks
from app.analytics.blocks import E, L
from app.analytics.context import MetricContext
from app.models.enums import AccountingDirection
from app.models.masters import CostCentre, Group
from app.models.vouchers import CostCentreAllocation

NO_COST_CENTRE = "(No cost centre)"
GROUP_BY = {
    "ledger": ("ledger_id", "ledger_name"),
    "group": ("group_id", "group_name"),
    "cost_centre": ("cost_centre_id", "cost_centre_name"),
}
FILTERS = {"cost_centre": "cost_centre_id"}  # FR-4.3 (D-053 #1)


def detail_query(ctx: MetricContext) -> Select[Any]:
    a = CostCentreAllocation
    mine = a.company_id == ctx.company_id
    # Per entry: each allocation (+), and minus their sum (the remainder's offset).
    parts = union_all(
        select(a.voucher_entry_id, a.cost_centre_id, a.amount_absolute.label("part")).where(mine),
        select(a.voucher_entry_id, null(), -func.sum(a.amount_absolute))
        .where(mine)
        .group_by(a.voucher_entry_id),
    ).subquery()
    anchor, centre = aliased(Group), aliased(CostCentre)
    sign = case((E.accounting_direction == AccountingDirection.DEBIT, 1), else_=-1)
    split = parts.c.voucher_entry_id.is_not(None)
    amount = case(
        (~split, E.amount_signed),
        (parts.c.cost_centre_id.is_(None), sign * (E.amount_absolute + parts.c.part)),
        else_=sign * parts.c.part,
    )
    return (
        blocks.entries(ctx, amount)
        .add_columns(
            anchor.group_id,
            anchor.name.label("group_name"),
            centre.cost_centre_id,
            func.coalesce(centre.name, literal(NO_COST_CENTRE)).label("cost_centre_name"),
        )
        .join(anchor, anchor.group_id == L.classification_group_id)
        .outerjoin(parts, parts.c.voucher_entry_id == E.voucher_entry_id)
        .outerjoin(
            centre,
            and_(
                centre.company_id == ctx.company_id,
                centre.cost_centre_id == parts.c.cost_centre_id,
            ),
        )
        .where(
            blocks.in_class(ctx.classes.expense),
            # drop a remainder row that is zero (the entry is fully allocated)
            or_(~split, parts.c.cost_centre_id.is_not(None), E.amount_absolute + parts.c.part != 0),
        )
    )
