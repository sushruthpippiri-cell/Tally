"""The product difference (ACC-1.9, ACC-1.10, D-053 #3): Total Sales Revenue less
Product-attributed Revenue, shown under exactly one label (`query.difference_label`,
ACC-VAL-1). Rows: the sales rows (+) and inventory lines (-) of the vouchers where they do not
cancel out, so grouped by voucher it is the list of contributing vouchers (FR-DD-4). See
`returns.sales_less_products`.
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import returns
from app.analytics.context import MetricContext

GROUP_BY = {"voucher": ("voucher_id", "voucher_number")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    return returns.sales_less_products(ctx)
