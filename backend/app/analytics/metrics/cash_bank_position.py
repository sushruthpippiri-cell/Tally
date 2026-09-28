"""Cash and bank position on date D (ACC-9.3): the balances of the ledgers in the Cash/Bank
allow-list. A Bank OD ledger counts only if it is added to that list.

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


def detail_query(ctx: MetricContext) -> Select[Any]:
    return blocks.balance_rows(ctx, blocks.in_class(ctx.classes.cash_bank))
