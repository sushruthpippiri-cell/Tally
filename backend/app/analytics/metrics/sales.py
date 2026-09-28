"""Total Sales Revenue (ACC-1.1, ACC-2.1, ACC-2.2, ACC-5.1, ACC-8.2).

CREDIT entries on Sales-class ledgers in ACTIVE vouchers of base type SALES (+), minus the
DEBIT entries on Sales-class ledgers in linked credit notes (-). Tax-class ledgers count only
when taxable-value mode is off. See `returns.gross_less_returns`.
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import returns
from app.analytics.context import MetricContext

GROUP_BY = {"ledger": ("ledger_id", "ledger_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    return returns.gross_less_returns(ctx, returns.CREDIT_NOTE)
