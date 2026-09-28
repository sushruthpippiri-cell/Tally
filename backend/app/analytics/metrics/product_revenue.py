"""Product-attributed Revenue (ACC-1.8, D-046 #2-3).

The inventory lines of ACTIVE vouchers of base type SALES (+) and of linked credit notes
(-): `voucher_items.amount`, with quantity and unit. What Total Sales Revenue holds beyond
this is the product difference (`query.product_difference`, ACC-1.9/1.10, D-046 #5).
"""

from typing import Any

from sqlalchemy import Select, and_, case, or_

from app.analytics import blocks, returns
from app.analytics.blocks import VT, V
from app.analytics.context import MetricContext
from app.models.enums import BaseVoucherType

GROUP_BY = {"product": ("stock_item_id", "stock_item_name")}


def detail_query(ctx: MetricContext) -> Select[Any]:
    sale = VT.base_voucher_type == BaseVoucherType.SALES
    returned = and_(
        VT.base_voucher_type == returns.CREDIT_NOTE,
        V.voucher_id.in_(
            returns.linked_notes(ctx.company_id, ctx.returns_linkable, returns.CREDIT_NOTE)
        ),
    )
    return blocks.items(ctx, case((sale, 1), else_=-1)).where(or_(sale, returned))
