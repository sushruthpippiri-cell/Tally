"""Cash flow (D-021, which supersedes ACC-1.6, 1.7, 3.3 and 3.4 as worded; ACC-3.1).

Every movement on Cash/Bank-list ledgers on vouchers of any base type counts, netted per
voucher: one row per voucher, `amount` = Σ `amount_signed` (debit +) of its entries on list
ledgers. A positive net is an INFLOW, a negative one an OUTFLOW; a transfer between the
company's own listed cash and bank ledgers nets to zero and is left out, while a transfer to
a ledger outside the list (an unlisted Bank OD) counts. Journals count unless
`cashflow.include_journal` is off. So for any period the net equals the change in the
Cash/Bank position (`cash_bank_position`) over it.
"""

from typing import Any

from sqlalchemy import Select, String, case, cast, func, null, select
from sqlalchemy.dialects.postgresql import UUID

from app.analytics import blocks
from app.analytics.blocks import VT, E
from app.analytics.context import MetricContext
from app.models.enums import BaseVoucherType

KIND = "flow"
GROUP_BY = {"flow": ("flow", "flow")}
NOTE = (
    "Cash flow counts every movement on the Cash/Bank list, netted per voucher; transfers "
    "between the company's own listed cash and bank ledgers are left out (D-021)."
)


def detail_query(ctx: MetricContext) -> Select[Any]:
    moved = blocks.entries(ctx, E.amount_signed).where(blocks.in_class(ctx.classes.cash_bank))
    if not ctx.include_journal:
        moved = moved.where(VT.base_voucher_type != BaseVoucherType.JOURNAL)
    r = moved.subquery()
    net = func.sum(r.c.amount)
    return (
        select(
            r.c.voucher_id,
            r.c.voucher_date,
            r.c.voucher_number,
            r.c.voucher_type_name,
            r.c.base_voucher_type,
            cast(null(), UUID(as_uuid=True)).label("ledger_id"),
            cast(null(), String).label("ledger_name"),
            net.label("amount"),
            case((net > 0, "INFLOW"), else_="OUTFLOW").label("flow"),
        )
        .group_by(
            r.c.voucher_id,
            r.c.voucher_date,
            r.c.voucher_number,
            r.c.voucher_type_name,
            r.c.base_voucher_type,
        )
        .having(net != 0)
    )
