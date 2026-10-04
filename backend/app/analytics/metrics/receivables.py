"""Total receivables on date D (ACC-9.4): the balances of ledgers anchored at Sundry Debtors.

Rows: each ledger's books-beginning opening and every entry from `books_from` to
`filter.date_to` (`blocks.balance_rows`, D-039 #5). A ledger with no opening makes the figure
"opening balance unavailable" (ACC-9.6, D-045 #3).
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import blocks
from app.analytics.context import MetricContext

KIND = "balance"
GROUP_BY = {"ledger": ("ledger_id", "ledger_name")}
FILTERS = {"customer": "ledger_id"}  # FR-4.3 (D-053 #1)


def detail_query(ctx: MetricContext) -> Select[Any]:
    return blocks.balance_rows(ctx, blocks.in_class(ctx.classes.customer))
