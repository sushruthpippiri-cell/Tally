"""Returns (ACC-5.x): which credit and debit notes are linked to an original bill.

A Credit Note (Debit Note) is a Sales (Purchase) Return only when one of its AGST_REF bill
allocations names the same `(ledger, reference)` as a NEW_REF created by an ACTIVE SALES
(PURCHASE) voucher. How that link appears in Tally's export is gate G26: until it passes, no
note is linked and every note is unclassified (ACC-5.5).
"""

import uuid
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    String,
    and_,
    case,
    cast,
    false,
    func,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import aliased

from app.analytics.blocks import VT, E, L, V, entries, in_class, items, party_bucket
from app.analytics.context import MetricContext
from app.models.enums import (
    AccountingDirection,
    AllocationType,
    BaseVoucherType,
    VoucherStatus,
)
from app.models.vouchers import BillAllocation

CREDIT_NOTE, DEBIT_NOTE = BaseVoucherType.CREDIT_NOTE, BaseVoucherType.DEBIT_NOTE
ORIGIN = {CREDIT_NOTE: BaseVoucherType.SALES, DEBIT_NOTE: BaseVoucherType.PURCHASE}
UNLINKED = {CREDIT_NOTE: "UNLINKED_CREDIT_NOTE", DEBIT_NOTE: "UNLINKED_DEBIT_NOTE"}  # ACC-5.3


def note_origins(company_id: uuid.UUID, linkable: bool, note: BaseVoucherType) -> Select[Any]:
    """(note_id, origin_id): each note of this kind and the original voucher it is linked to,
    through an AGST_REF naming the same `(ledger, reference)` as a NEW_REF on an ACTIVE SALES
    (PURCHASE) voucher (ACC-5.1, 5.2). Empty until gate G26 passes (ACC-5.5)."""
    if not linkable:  # GATE-G26
        return select(V.voucher_id.label("note_id"), V.voucher_id.label("origin_id")).where(false())
    agst, ref = aliased(BillAllocation), aliased(BillAllocation)
    ref_entry, ref_voucher, ref_type = aliased(E), aliased(V), aliased(VT)
    return (
        select(V.voucher_id.label("note_id"), ref_voucher.voucher_id.label("origin_id"))
        .select_from(agst)
        .join(E, and_(E.company_id == agst.company_id, E.voucher_entry_id == agst.voucher_entry_id))
        .join(V, and_(V.company_id == E.company_id, V.voucher_id == E.voucher_id))
        .join(VT, and_(VT.company_id == V.company_id, VT.voucher_type_id == V.voucher_type_id))
        .join(
            ref,
            and_(
                ref.company_id == agst.company_id,
                ref.ledger_id == agst.ledger_id,
                ref.reference_name == agst.reference_name,
                ref.allocation_type == AllocationType.NEW_REF,
            ),
        )
        .join(
            ref_entry,
            and_(
                ref_entry.company_id == ref.company_id,
                ref_entry.voucher_entry_id == ref.voucher_entry_id,
            ),
        )
        .join(
            ref_voucher,
            and_(
                ref_voucher.company_id == ref_entry.company_id,
                ref_voucher.voucher_id == ref_entry.voucher_id,
            ),
        )
        .join(
            ref_type,
            and_(
                ref_type.company_id == ref_voucher.company_id,
                ref_type.voucher_type_id == ref_voucher.voucher_type_id,
            ),
        )
        .where(
            agst.company_id == company_id,
            agst.allocation_type == AllocationType.AGST_REF,
            VT.base_voucher_type == note,
            ref_voucher.status == VoucherStatus.ACTIVE,
            ref_type.base_voucher_type == ORIGIN[note],
        )
        .distinct()
    )


def linked_notes(
    company_id: uuid.UUID, linkable: bool, note: BaseVoucherType
) -> Select[tuple[uuid.UUID]]:
    """Voucher ids of the notes of this kind that are linked (ACC-5.1, 5.2)."""
    origins = note_origins(company_id, linkable, note).subquery()
    return select(origins.c.note_id).distinct()


def return_entries(ctx: MetricContext, note: BaseVoucherType) -> ColumnElement[bool]:
    """The entries of a note that reverse sales (purchases): DEBIT (CREDIT) entries on
    Sales-class (Purchase-class) ledgers, and on tax ledgers only when taxable-value mode is
    off (ACC-2.2)."""
    goods = ctx.classes.sales if note is CREDIT_NOTE else ctx.classes.purchase
    tax: Any = () if ctx.taxable_value_mode else ctx.classes.tax
    direction = AccountingDirection.DEBIT if note is CREDIT_NOTE else AccountingDirection.CREDIT
    return and_(
        VT.base_voucher_type == note,
        E.accounting_direction == direction,
        in_class(goods, tax),
    )


def is_linked(ctx: MetricContext, note: BaseVoucherType) -> ColumnElement[bool]:
    return E.voucher_id.in_(linked_notes(ctx.company_id, ctx.returns_linkable, note))


def gross_less_returns(ctx: MetricContext, note: BaseVoucherType) -> Select[Any]:
    """Sales (for CREDIT_NOTE) or purchases (for DEBIT_NOTE), single-sided (ACC-1.1, 1.2):
    CREDIT (DEBIT) entries on Sales-class (Purchase-class) ledgers in ACTIVE vouchers of base
    type SALES (PURCHASE), positive, plus the linked notes' reversing entries, negative. Tax
    ledgers count only when taxable-value mode is off (ACC-2.2). The other side of the voucher
    is never read, so nothing is counted twice (ACC-2.1)."""
    origin = ORIGIN[note]
    goods = ctx.classes.sales if note is CREDIT_NOTE else ctx.classes.purchase
    tax: Any = () if ctx.taxable_value_mode else ctx.classes.tax
    direction = AccountingDirection.CREDIT if note is CREDIT_NOTE else AccountingDirection.DEBIT
    original = and_(
        VT.base_voucher_type == origin,
        E.accounting_direction == direction,
        in_class(goods, tax),
    )
    reversed_ = and_(return_entries(ctx, note), is_linked(ctx, note))
    amount = case((VT.base_voucher_type == origin, E.amount_absolute), else_=-E.amount_absolute)
    return entries(ctx, amount).where(or_(original, reversed_))


def attributed(ctx: MetricContext, note: BaseVoucherType) -> Select[Any]:
    """The rows of `gross_less_returns`, each with its party bucket (ACC-6.1-6.4, ACC-1.4):
    `party_id` / `party_name`, or NULL for Unattributed. A sale or purchase is attributed to
    the one customer (supplier) among its entries, else Unattributed. A linked return takes
    its original's bucket; a note whose originals are in different buckets is Unattributed,
    never split (D-046 #1). The rows are exactly those of sales (purchases), so the buckets
    always total the metric."""
    party = ctx.classes.customer if note is CREDIT_NOTE else ctx.classes.supplier
    rows = gross_less_returns(ctx, note).cte("sale_rows")
    # One set of buckets, for the sales (purchases) and for the originals of the returns.
    bucket = party_bucket(ctx, party, ORIGIN[note]).cte("party_buckets")
    origins = note_origins(ctx.company_id, ctx.returns_linkable, note).subquery()
    theirs = bucket.alias("origin_buckets")
    agreed = func.array_agg(theirs.c.party_id.distinct(), type_=ARRAY(UUID(as_uuid=True)))
    origin_bucket = (
        select(
            origins.c.note_id,
            case((func.cardinality(agreed) == 1, agreed[1])).label("party_id"),
        )
        .outerjoin(theirs, theirs.c.voucher_id == origins.c.origin_id)
        .group_by(origins.c.note_id)
        .subquery()
    )
    # Sales rows take their own voucher's bucket, return rows their originals': two joins
    # over disjoint rows, so neither is ever evaluated for the other's rows.
    sold = (
        select(rows, bucket.c.party_id)
        .outerjoin(bucket, bucket.c.voucher_id == rows.c.voucher_id)
        .where(rows.c.base_voucher_type == ORIGIN[note])
    )
    returned = (
        select(rows, origin_bucket.c.party_id)
        .outerjoin(origin_bucket, origin_bucket.c.note_id == rows.c.voucher_id)
        .where(rows.c.base_voucher_type != ORIGIN[note])
    )
    both = union_all(sold, returned).subquery()
    ledger = aliased(L)
    return select(both, ledger.name.label("party_name")).outerjoin(
        ledger, and_(ledger.company_id == ctx.company_id, ledger.ledger_id == both.c.party_id)
    )


def product_lines(ctx: MetricContext) -> Select[Any]:
    """Product-attributed Revenue's rows (ACC-1.8, D-046 #2-3): the inventory lines of
    vouchers of base type SALES (+) and of linked credit notes (-)."""
    sale = VT.base_voucher_type == BaseVoucherType.SALES
    returned = and_(
        VT.base_voucher_type == CREDIT_NOTE,
        V.voucher_id.in_(linked_notes(ctx.company_id, ctx.returns_linkable, CREDIT_NOTE)),
    )
    return items(ctx, case((sale, 1), else_=-1)).where(or_(sale, returned))


def sales_less_products(ctx: MetricContext) -> Select[Any]:
    """The product difference's rows (ACC-1.9/1.10, D-053 #3): Total Sales Revenue's rows (+)
    and Product-attributed Revenue's lines (-), on the vouchers where they do not cancel out.
    So its total is Total Sales Revenue - Product-attributed Revenue, and its vouchers are the
    ones that contribute to the difference (FR-DD-4)."""
    sold = gross_less_returns(ctx, CREDIT_NOTE).add_columns(
        cast(null(), UUID(as_uuid=True)).label("stock_item_id"),
        cast(null(), String).label("stock_item_name"),
    )
    lines = product_lines(ctx).subquery()
    unsold = select(
        lines.c.voucher_id,
        lines.c.voucher_date,
        lines.c.voucher_number,
        lines.c.voucher_type_name,
        lines.c.base_voucher_type,
        lines.c.ledger_id,
        lines.c.ledger_name,
        (-lines.c.amount).label("amount"),
        lines.c.stock_item_id,
        lines.c.stock_item_name,
    )
    rows = union_all(sold, unsold).subquery()
    contributing = (
        select(rows.c.voucher_id).group_by(rows.c.voucher_id).having(func.sum(rows.c.amount) != 0)
    )
    return select(rows).where(rows.c.voucher_id.in_(contributing))
