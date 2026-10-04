"""Product-attributed Revenue (ACC-1.8, D-046 #2-3).

The inventory lines of ACTIVE vouchers of base type SALES (+) and of linked credit notes
(-): `voucher_items.amount`, with quantity and unit (`returns.product_lines`). What Total
Sales Revenue holds beyond this is the product difference (`metrics/product_difference.py`,
ACC-1.9/1.10, D-046 #5).
"""

from typing import Any

from sqlalchemy import Select

from app.analytics import returns
from app.analytics.context import MetricContext

GROUP_BY = {"product": ("stock_item_id", "stock_item_name")}
FILTERS = {"product": "stock_item_id"}  # FR-4.3 (D-053 #1)


def detail_query(ctx: MetricContext) -> Select[Any]:
    return returns.product_lines(ctx)
