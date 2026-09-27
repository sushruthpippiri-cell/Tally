"""Record lifecycle across syncs (SRS 6.7, 6.10, D-041 #4): a record that is present again
returns to ACTIVE, whatever its ALTERID. Stale protection treats an equal ALTERID as "no
change", so a record wrongly marked MISSING_IN_TALLY would otherwise stay missing forever."""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.enums import CollectionType, MasterStatus
from app.models.masters import CostCentre, Group, Ledger, StockItem, VoucherType
from app.models.vouchers import Voucher
from tally_contract.log import get_logger

log = get_logger(__name__)

MISSING = MasterStatus.MISSING_IN_TALLY.value  # the same value for vouchers
ACTIVE = MasterStatus.ACTIVE.value

# collection -> (model, primary key); the tables a key list or a pull can speak for
TABLES: dict[CollectionType, tuple[Any, Any]] = {
    CollectionType.GROUP: (Group, Group.group_id),
    CollectionType.LEDGER: (Ledger, Ledger.ledger_id),
    CollectionType.VOUCHER_TYPE: (VoucherType, VoucherType.voucher_type_id),
    CollectionType.STOCK_ITEM: (StockItem, StockItem.stock_item_id),
    CollectionType.COST_CENTRE: (CostCentre, CostCentre.cost_centre_id),
    CollectionType.VOUCHER: (Voucher, Voucher.voucher_id),
}


async def restore(
    session: AsyncSession,
    company_id: uuid.UUID,
    collection: CollectionType,
    guids: Iterable[str] | Select[Any],
    source: str,
) -> int:
    """MISSING_IN_TALLY records among `guids` -> ACTIVE, each audited REAPPEARED (DR-ML-4)."""
    model, pk = TABLES[collection]
    rows = await session.execute(
        update(model)
        .where(model.company_id == company_id, model.status == MISSING, model.tally_guid.in_(guids))
        .values(status=ACTIVE)
        .returning(pk, model.tally_guid)
        .execution_options(synchronize_session=False)
    )
    restored = rows.all()
    for record_id, guid in restored:
        await audit.record(
            session,
            company_id=company_id,
            user_id=None,
            action="REAPPEARED",
            entity_type=model.__tablename__,
            entity_id=str(record_id),
            before={"status": MISSING},
            after={"status": ACTIVE, "tally_guid": guid, "source": source},
        )
        log.info("record_reappeared", collection=collection.value, guid=guid, source=source)
    return len(restored)
