"""PAYMENTS on the reconciliation basis (D-048 #4, docs/reconciliation-basis.md): the CREDIT
entries on Cash/Bank-list ledgers in ACTIVE vouchers of base type PAYMENT, as positive amounts.

Not a dashboard figure: the dashboard's cash flow nets every voucher type (D-021). This is the
same aggregation Tally's totals are compared on, so the two measure the same thing (D-008).
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import blocks
from app.analytics.blocks import VT, E
from app.analytics.context import MetricContext
from app.models.enums import AccountingDirection, BaseVoucherType

GROUP_BY = {"ledger": ("ledger_id", "ledger_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    return blocks.entries(ctx, E.amount_absolute).where(
        VT.base_voucher_type == BaseVoucherType.PAYMENT,
        E.accounting_direction == AccountingDirection.CREDIT,
        blocks.in_class(ctx.classes.cash_bank),
    )
