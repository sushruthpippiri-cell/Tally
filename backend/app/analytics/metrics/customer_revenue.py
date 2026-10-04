"""Customer-attributed Revenue and Unattributed Customer Revenue (ACC-6.1-6.4, D-046 #1).

The rows of Total Sales Revenue, each with its customer: the one customer ledger among a
sale's entries, or NULL (Unattributed: a cash sale, or several customers, never split). A
linked return comes off its original sale's bucket. Same rows as `sales`, so the customers
plus Unattributed always total Total Sales Revenue (ACC-6.4). See `returns.attributed`.
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import returns
from app.analytics.context import MetricContext

UNATTRIBUTED = "Unattributed Customer Revenue"
GROUP_BY = {"customer": ("party_id", "party_name")}
FILTERS = {"customer": "party_id"}  # FR-4.3 (D-053 #1)


def detail_query(ctx: MetricContext) -> Select[Any]:
    return returns.attributed(ctx, returns.CREDIT_NOTE)
