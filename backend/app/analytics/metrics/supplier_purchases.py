"""Supplier-attributed purchases and Unattributed Supplier Purchases (ACC-1.4, D-046 #1).

The rows of Purchase Value, each with its supplier: the one supplier ledger among a
purchase's entries, or NULL (Unattributed). A linked purchase return comes off its original
purchase's bucket. Same rows as `purchases`, so they always total Purchase Value.
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import returns
from app.analytics.context import MetricContext

UNATTRIBUTED = "Unattributed Supplier Purchases"
GROUP_BY = {"supplier": ("party_id", "party_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    return returns.attributed(ctx, returns.DEBIT_NOTE)
