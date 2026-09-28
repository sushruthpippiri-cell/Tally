"""Building blocks every metric's detail query starts from (P8.2, D-044 #1).

Only the normalized amount columns are read: `accounting_direction`, `amount_absolute`,
`amount_signed` (ACC-DATA-1).
"""

import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, false, select

from app.analytics.context import MetricContext
from app.models.masters import Ledger, VoucherType
from app.models.vouchers import Voucher, VoucherEntry

E, V, VT, L = VoucherEntry, Voucher, VoucherType, Ledger


def entries(ctx: MetricContext, amount: ColumnElement[Decimal]) -> Select[Any]:
    """One row per voucher entry dated in the filter's range on a voucher with one of its
    statuses (ACTIVE unless widened, ACC-4.5), with the standard detail columns and `amount`,
    the metric's signed contribution. Metrics add their own conditions."""
    return (
        select(
            V.voucher_id,
            V.voucher_date,
            V.voucher_number,
            VT.name.label("voucher_type_name"),
            VT.base_voucher_type,
            E.ledger_id,
            L.name.label("ledger_name"),
            amount.label("amount"),
        )
        .select_from(E)
        .join(V, and_(V.company_id == E.company_id, V.voucher_id == E.voucher_id))
        .join(VT, and_(VT.company_id == V.company_id, VT.voucher_type_id == V.voucher_type_id))
        .join(L, and_(L.company_id == E.company_id, L.ledger_id == E.ledger_id))
        .where(
            E.company_id == ctx.company_id,
            V.company_id == ctx.company_id,
            V.status.in_(ctx.filter.statuses),
            V.voucher_date.between(ctx.filter.date_from, ctx.filter.date_to),
        )
    )


def in_class(*classes: Iterable[uuid.UUID]) -> ColumnElement[bool]:
    """The entry's ledger is anchored in one of these classes; a ledger with no anchor
    (unresolved chain, ACC-7.4) never is."""
    ids = {g for c in classes for g in c}
    return L.classification_group_id.in_(ids) if ids else false()
