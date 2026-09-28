"""Unclassified Adjustments (ACC-5.3, 5.4): credit and debit notes with no resolvable link to
an original bill. They are never subtracted from sales or purchases; this lists what they would
have reversed (the note's entries on Sales- or Purchase-class ledgers), as a positive amount."""

from typing import Any

from sqlalchemy import Select, and_, case, not_, or_

from app.analytics import blocks, returns
from app.analytics.blocks import VT, E
from app.analytics.context import MetricContext
from app.analytics.returns import CREDIT_NOTE, DEBIT_NOTE, UNLINKED

GROUP_BY = {
    "type": ("adjustment_type", "adjustment_type"),
    "ledger": ("ledger_id", "ledger_name"),
}


def detail_query(ctx: MetricContext) -> Select[Any]:
    kind = case(
        (VT.base_voucher_type == CREDIT_NOTE, UNLINKED[CREDIT_NOTE]),
        else_=UNLINKED[DEBIT_NOTE],
    )
    return (
        blocks.entries(ctx, E.amount_absolute)
        .add_columns(kind.label("adjustment_type"))
        .where(
            or_(
                *(
                    and_(returns.return_entries(ctx, note), not_(returns.is_linked(ctx, note)))
                    for note in (CREDIT_NOTE, DEBIT_NOTE)
                )
            )
        )
    )
