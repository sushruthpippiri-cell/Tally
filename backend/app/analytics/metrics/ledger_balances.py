"""Every classified ledger's balance (ACC-9.1 as amended by D-039 #5, ACC-9.2).

A balance-sheet ledger (anchor nature ASSET or LIABILITY) on `filter.date_to`: its
books-beginning opening plus every entry since `books_from`. An income or expense ledger:
its movement in [date_from, date_to] only, so it never carries into the next year. Ledgers
with an unresolved chain have no nature and are left out (ACC-7.4).
"""

from typing import Any

from sqlalchemy import Select, select, union_all

from app.analytics import blocks
from app.analytics.blocks import E
from app.analytics.context import MetricContext
from app.models.enums import Nature

KIND = "balance"
GROUP_BY = {"ledger": ("ledger_id", "ledger_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    balance_sheet = blocks.balance_rows(ctx, blocks.nature_in(ctx, Nature.ASSET, Nature.LIABILITY))
    income_expense = blocks.entries(ctx, E.amount_signed).where(
        blocks.nature_in(ctx, Nature.INCOME, Nature.EXPENSE)
    )
    return select(union_all(balance_sheet, income_expense).subquery())
