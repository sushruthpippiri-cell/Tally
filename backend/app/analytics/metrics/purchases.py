"""Purchase Value (ACC-1.2, ACC-2.x, ACC-5.2): the mirror of sales.

DEBIT entries on Purchase-class ledgers in ACTIVE vouchers of base type PURCHASE (+), minus the
CREDIT entries on Purchase-class ledgers in linked debit notes (-); tax only when
taxable-value mode is off. See `returns.gross_less_returns`.
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import returns
from app.analytics.context import MetricContext

GROUP_BY = {"ledger": ("ledger_id", "ledger_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    return returns.gross_less_returns(ctx, returns.DEBIT_NOTE)
