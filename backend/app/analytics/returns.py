"""Returns (ACC-5.x): which credit and debit notes are linked to an original bill.

A Credit Note (Debit Note) is a Sales (Purchase) Return only when one of its AGST_REF bill
allocations names the same `(ledger, reference)` as a NEW_REF created by an ACTIVE SALES
(PURCHASE) voucher. How that link appears in Tally's export is gate G26: until it passes, no
note is linked and every note is unclassified (ACC-5.5).
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, exists, false, or_, select
from sqlalchemy.orm import aliased

from app.analytics.blocks import VT, E, V, entries, in_class
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


def linked_notes(
    company_id: uuid.UUID, linkable: bool, note: BaseVoucherType
) -> Select[tuple[uuid.UUID]]:
    """Voucher ids of the notes of this kind that are linked (ACC-5.1, 5.2)."""
    if not linkable:  # GATE-G26
        return select(V.voucher_id).where(false())
    agst, ref = aliased(BillAllocation), aliased(BillAllocation)
    ref_entry, ref_voucher, ref_type = aliased(E), aliased(V), aliased(VT)
    original_bill = (
        select(ref.id)
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
            ref.company_id == company_id,
            ref.allocation_type == AllocationType.NEW_REF,
            ref.ledger_id == agst.ledger_id,
            ref.reference_name == agst.reference_name,
            ref_voucher.status == VoucherStatus.ACTIVE,
            ref_type.base_voucher_type == ORIGIN[note],
        )
    )
    return (
        select(V.voucher_id)
        .select_from(agst)
        .join(E, and_(E.company_id == agst.company_id, E.voucher_entry_id == agst.voucher_entry_id))
        .join(V, and_(V.company_id == E.company_id, V.voucher_id == E.voucher_id))
        .join(VT, and_(VT.company_id == V.company_id, VT.voucher_type_id == V.voucher_type_id))
        .where(
            agst.company_id == company_id,
            agst.allocation_type == AllocationType.AGST_REF,
            VT.base_voucher_type == note,
            exists(original_bill),
        )
        .distinct()
    )


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
