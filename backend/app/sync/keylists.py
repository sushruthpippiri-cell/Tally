"""Deletion detection by key list (SYNC-5.x, D-007, D-041).

A key list is the collection's GUIDs and ALTERIDs from its key-only report, which repeats the
same Collection as the data pull (D-041 #2). It is staged chunk by chunk, then evaluated once,
in one transaction, under the same guard as a batch (D-039 #1):

- candidates: ACTIVE local records of the collection inside the list's window
- missing: candidates without a key -> MISSING_IN_TALLY, unless the D-007 guard fires
- reappeared: MISSING_IN_TALLY records with a key -> ACTIVE, whatever the ALTERID
- missed changes: keys newer than the stored record yet within the watermark -> the watermark
  is lowered so the next run re-pulls them
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.core.gates import collection_sync_mode
from app.core.permissions import CompanyContext, scoped
from app.models.enums import CollectionType, KeyListStatus
from app.models.sync import SyncKeyList, SyncKeyListKey, SyncWatermark
from app.models.vouchers import Voucher
from app.schemas.sync import KeyListOut
from app.services.settings import get_setting
from app.services.sync_runs import open_run
from app.sync import lifecycle
from app.sync.context import in_param_batches
from app.sync.ingest import chunk_guard, major
from tally_contract.errors import ErrorCode
from tally_contract.log import get_logger
from tally_contract.records import KeyListChunk
from tally_contract.version import CONTRACT_VERSION

log = get_logger(__name__)

GUARD_FLOOR = 5  # D-007 as amended by the owner: small collections are protected too


def _out(kl: SyncKeyList) -> KeyListOut:
    expected = range(kl.final_seq + 1) if kl.final_seq is not None else range(0)
    return KeyListOut(
        list_id=kl.list_id,
        collection_type=CollectionType(kl.collection_type),
        status=KeyListStatus(kl.status),
        received_chunks=list(kl.received_chunks),
        waiting_for=[n for n in expected if n not in kl.received_chunks],
        keys_count=kl.keys_count,
        candidates=kl.candidates,
        marked_missing=kl.marked_missing,
        reappeared=kl.reappeared,
        missed_changes=kl.missed_changes,
    )


def _invalid(message: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, message, 422)


async def receive(
    session: AsyncSession, agent: AgentContext, command_id: uuid.UUID, chunk: KeyListChunk
) -> KeyListOut:
    if major(chunk.contract_version) != major(CONTRACT_VERSION):
        raise _invalid(
            f"Contract {chunk.contract_version} is not compatible with {CONTRACT_VERSION}"
        )
    run, _ = await open_run(session, agent, chunk.sync_run_id)
    if run.command_id != command_id:
        raise AppError(ErrorCode.NOT_FOUND, "Sync run not found", 404)
    collection = chunk.collection_type
    watermark = await chunk_guard(session, agent, command_id, collection)
    date_from = chunk.window.date_from if chunk.window else None
    date_to = chunk.window.date_to if chunk.window else None
    await session.execute(
        insert(SyncKeyList)
        .values(
            list_id=chunk.list_id,
            company_id=agent.company_id,
            sync_run_id=run.sync_run_id,
            collection_type=collection.value,
            date_from=date_from,
            date_to=date_to,
        )
        .on_conflict_do_nothing(index_elements=[SyncKeyList.list_id])
    )
    kl = (
        await session.execute(
            select(SyncKeyList)
            .where(SyncKeyList.list_id == chunk.list_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if kl.company_id != agent.company_id or kl.sync_run_id != run.sync_run_id:
        raise AppError(ErrorCode.NOT_FOUND, "Key list not found", 404)
    if (kl.collection_type, kl.date_from, kl.date_to) != (collection.value, date_from, date_to):
        raise _invalid("Every chunk of a key list must name the same collection and window")
    if kl.status != KeyListStatus.RECEIVING:  # a replay after evaluation, or abandoned
        await session.commit()
        return _out(kl)
    if chunk.chunk_seq not in kl.received_chunks:
        keys = [
            {
                "list_id": kl.list_id,
                "company_id": agent.company_id,
                "tally_guid": k.guid,
                "alter_id": k.alter_id,
            }
            for k in chunk.keys
        ]
        # Four columns per key, so one statement holds at most ~8,000 of them; a voucher key
        # list for a real company arrives in far larger chunks than that (P16.5).
        for batch in in_param_batches(keys, columns=4):
            await session.execute(insert(SyncKeyListKey).values(batch).on_conflict_do_nothing())
        kl.received_chunks = sorted([*kl.received_chunks, chunk.chunk_seq])
    if chunk.is_final:
        if kl.final_seq is not None and kl.final_seq != chunk.chunk_seq:
            raise _invalid(f"The key list already ended at chunk {kl.final_seq}")
        kl.final_seq = chunk.chunk_seq
    await session.flush()
    if kl.final_seq is not None and set(range(kl.final_seq + 1)) <= set(kl.received_chunks):
        await _evaluate(session, kl, watermark, datetime.now(UTC))
    await session.commit()
    return _out(kl)


async def _waived(session: AsyncSession, kl: SyncKeyList) -> bool:
    """An Owner/Admin confirmed a suspicious list after this collection's last evaluation."""
    same = (SyncKeyList.company_id == kl.company_id) & (
        SyncKeyList.collection_type == kl.collection_type
    )
    last = await session.scalar(select(func.max(SyncKeyList.evaluated_at)).where(same))
    confirmed = select(SyncKeyList.list_id).where(
        same, SyncKeyList.status == KeyListStatus.CONFIRMED
    )
    if last is not None:
        confirmed = confirmed.where(SyncKeyList.confirmed_at > last)
    return (await session.scalar(select(exists(confirmed)))) or False


async def _evaluate(session: AsyncSession, kl: SyncKeyList, watermark: int, now: datetime) -> None:
    collection = CollectionType(kl.collection_type)
    model, pk = lifecycle.TABLES[collection]
    keyed = select(SyncKeyListKey.tally_guid).where(SyncKeyListKey.list_id == kl.list_id)
    kl.keys_count = int(
        await session.scalar(select(func.count()).select_from(keyed.subquery())) or 0
    )

    # Presence is proof: reappearance never waits for the guard or the ALTERID (D-041 #4).
    kl.reappeared = await lifecycle.restore(session, kl.company_id, collection, keyed, "key list")

    in_scope: list[Any] = [model.company_id == kl.company_id, model.status == lifecycle.ACTIVE]
    if kl.date_from is not None:  # only records inside the list's own window (owner item 5)
        in_scope.append(Voucher.voucher_date.between(kl.date_from, kl.date_to))
    absent = ~exists().where(
        SyncKeyListKey.list_id == kl.list_id, SyncKeyListKey.tally_guid == model.tally_guid
    )
    kl.candidates = int(await session.scalar(select(func.count(pk)).where(*in_scope)) or 0)
    missing = int(await session.scalar(select(func.count(pk)).where(*in_scope, absent)) or 0)
    ratio = Decimal(
        str(await get_setting(session, kl.company_id, "sync.keylist_max_missing_ratio"))
    )
    limit: Decimal = max(Decimal(GUARD_FLOOR), ratio * kl.candidates)
    suspicious: bool = kl.candidates > 0 and (kl.keys_count == 0 or missing > limit)  # D-007
    waived = await _waived(session, kl)
    kl.guard_waived = suspicious and waived
    if suspicious and not waived:
        kl.status = KeyListStatus.SUSPICIOUS
        log.warning(
            "key_list_suspicious",
            code=ErrorCode.KEY_LIST_SUSPICIOUS.value,
            collection=collection.value,
            list_id=str(kl.list_id),
            keys=kl.keys_count,
            candidates=kl.candidates,
            would_be_missing=missing,
        )
    else:
        kl.status = KeyListStatus.APPLIED
        rows = await session.execute(
            update(model)
            .where(*in_scope, absent)
            .values(status=lifecycle.MISSING)
            .returning(pk, model.tally_guid)
            .execution_options(synchronize_session=False)
        )
        marked = rows.all()
        for record_id, guid in marked:
            await audit.record(
                session,
                company_id=kl.company_id,
                user_id=None,
                action="MISSING_IN_TALLY",
                entity_type=model.__tablename__,
                entity_id=str(record_id),
                before={"status": lifecycle.ACTIVE},
                after={
                    "status": lifecycle.MISSING,
                    "tally_guid": guid,
                    "key_list": str(kl.list_id),
                },
            )
        kl.marked_missing = len(marked)

    await _missed_changes(session, kl, model, collection, watermark)
    await session.execute(delete(SyncKeyListKey).where(SyncKeyListKey.list_id == kl.list_id))
    kl.evaluated_at = now
    await session.flush()
    log.info(
        "key_list_evaluated",
        collection=collection.value,
        status=kl.status,
        missing=kl.marked_missing,
        reappeared=kl.reappeared,
    )


async def _missed_changes(
    session: AsyncSession, kl: SyncKeyList, model: Any, collection: CollectionType, watermark: int
) -> None:
    """Keys newer than what is stored yet within the watermark: a change was skipped. For an
    ALTERID-incremental collection the watermark moves below it (D-041 #5)."""
    newer = select(SyncKeyListKey.alter_id).where(
        SyncKeyListKey.list_id == kl.list_id,
        SyncKeyListKey.alter_id <= watermark,
        ~exists().where(
            model.company_id == kl.company_id,
            model.tally_guid == SyncKeyListKey.tally_guid,
            model.alter_id >= SyncKeyListKey.alter_id,
        ),
    )
    sub = newer.subquery()
    found = (await session.execute(select(func.count(), func.min(sub.c.alter_id)))).one()
    kl.missed_changes = int(found[0])
    if not kl.missed_changes or collection_sync_mode(collection.value) != "INCREMENTAL":
        return
    lowered = int(found[1]) - 1
    await session.execute(
        update(SyncWatermark)
        .where(
            SyncWatermark.company_id == kl.company_id,
            SyncWatermark.collection_type == collection.value,
        )
        .values(last_alter_id=lowered)
        .execution_options(synchronize_session=False)
    )
    log.warning(
        "key_list_missed_change",
        collection=collection.value,
        count=kl.missed_changes,
        watermark_from=watermark,
        watermark_to=lowered,
    )


async def confirm(session: AsyncSession, ctx: CompanyContext, list_id: uuid.UUID) -> KeyListOut:
    """D-041 #3: an Owner/Admin accepts that a suspicious list was a real bulk deletion; the
    guard is waived once, for the next list of that collection."""
    kl = (
        await session.execute(
            scoped(select(SyncKeyList), SyncKeyList, ctx)
            .where(SyncKeyList.list_id == list_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if kl is None:
        raise AppError(ErrorCode.NOT_FOUND, "Key list not found", 404)
    if kl.status != KeyListStatus.SUSPICIOUS:
        raise AppError(
            ErrorCode.CONFLICT,
            f"The key list is {kl.status}; only a suspicious one can be confirmed",
            409,
        )
    kl.status = KeyListStatus.CONFIRMED
    kl.confirmed_by, kl.confirmed_at = ctx.user_id, datetime.now(UTC)
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="KEY_LIST_CONFIRMED",
        entity_type="sync_key_list",
        entity_id=str(kl.list_id),
        before={"status": KeyListStatus.SUSPICIOUS.value},
        after={"status": KeyListStatus.CONFIRMED.value, "collection_type": kl.collection_type},
    )
    await session.commit()
    return _out(kl)
