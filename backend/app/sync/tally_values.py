"""Tally's own figures for reconciliation (D-048 #7): staged per RECONCILIATION run, read only
by `app.reconciliation`. They touch no synced table, so they need no lease; a replayed batch
upserts the same rows. Only the normalized signed balance is kept, never Tally's raw text
(ACC-DATA-1)."""

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TallyValueKind
from app.models.sync import ReconciliationTallyValue
from tally_contract.records import (
    LedgerClosingBalanceRecord,
    ReconciliationStockRecord,
    ReconciliationTotalRecord,
)

KEY = ("kind", "entity_guid", "voucher_type_guid", "period_start", "period_end")


EMPTY = dict.fromkeys(("name", "debit", "credit", "value", "unit"))


def _row(record: Any) -> dict[str, Any]:
    return EMPTY | _values(record)  # one multi-row INSERT needs the same keys in every row


def _values(record: Any) -> dict[str, Any]:
    if isinstance(record, ReconciliationTotalRecord):
        return {
            "kind": TallyValueKind.TOTAL,
            "entity_guid": record.ledger_guid,
            "voucher_type_guid": record.voucher_type_guid,
            "name": record.ledger_name,
            "period_start": record.period_start,
            "period_end": record.period_end,
            "debit": record.debit,
            "credit": record.credit,
        }
    if isinstance(record, LedgerClosingBalanceRecord):
        return {
            "kind": TallyValueKind.LEDGER_CLOSING,
            "entity_guid": record.ledger_guid,
            "voucher_type_guid": "",
            "name": record.ledger_name,
            "period_start": record.as_of_date,
            "period_end": record.as_of_date,
            "value": record.balance.amount_signed,
        }
    assert isinstance(record, ReconciliationStockRecord)
    return {
        "kind": TallyValueKind.STOCK_CLOSING,
        "entity_guid": record.stock_item_guid,
        "voucher_type_guid": "",
        "period_start": record.as_of_date,
        "period_end": record.as_of_date,
        "value": record.closing_quantity,
        "unit": record.unit,
    }


async def write(
    session: AsyncSession, company_id: uuid.UUID, sync_run_id: uuid.UUID, records: list[Any]
) -> int:
    """Upsert the batch's values; within a batch the last one sent for a key wins."""
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        row = _row(record) | {"company_id": company_id, "sync_run_id": sync_run_id}
        rows[tuple(row[k] for k in KEY)] = row
    if not rows:
        return 0
    stmt = insert(ReconciliationTallyValue).values(list(rows.values()))
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_reconciliation_tally_values_key",
            set_={c: stmt.excluded[c] for c in ("name", "debit", "credit", "value", "unit")},
        )
    )
    return len(rows)
