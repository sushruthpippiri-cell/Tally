"""Total Sales Revenue (ACC-1.1, ACC-2.1, ACC-2.2, ACC-5.1, ACC-8.2).

CREDIT entries on Sales-class ledgers in ACTIVE vouchers of base type SALES (+), minus the
DEBIT entries on Sales-class ledgers in linked credit notes (-). Tax-class ledgers count only
when taxable-value mode is off. Never sums a voucher's entries as a whole: the debit side is
never read, so nothing is counted twice.
"""

from typing import Any

from sqlalchemy import Select, and_, case, or_

from app.analytics import blocks, returns
from app.analytics.blocks import VT, E
from app.analytics.context import MetricContext
from app.models.enums import AccountingDirection, BaseVoucherType


def detail_query(ctx: MetricContext) -> Select[Any]:
    tax: Any = () if ctx.taxable_value_mode else ctx.classes.tax
    is_sale = and_(
        VT.base_voucher_type == BaseVoucherType.SALES,
        E.accounting_direction == AccountingDirection.CREDIT,
        blocks.in_class(ctx.classes.sales, tax),
    )
    is_return = and_(
        returns.return_entries(ctx, returns.CREDIT_NOTE),
        returns.is_linked(ctx, returns.CREDIT_NOTE),
    )
    amount = case(
        (VT.base_voucher_type == BaseVoucherType.SALES, E.amount_absolute),
        else_=-E.amount_absolute,
    )
    return blocks.entries(ctx, amount).where(or_(is_sale, is_return))
