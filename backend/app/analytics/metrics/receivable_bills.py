"""Receivable bill allocations (SRS 10, D-049): one row per allocation on a customer ledger
(Sundry Debtors), with the opening bills, signed debit +. Summed only by
`app/analytics/aging.py`; not offered by the metric API."""

from typing import Any

from sqlalchemy import Select

from app.analytics import blocks
from app.analytics.context import MetricContext

GROUP_BY = {"ledger": ("ledger_id", "ledger_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    return blocks.bill_rows(ctx, ctx.classes.customer, debit_positive=True)
