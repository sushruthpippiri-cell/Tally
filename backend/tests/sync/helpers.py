"""Shared setup for ingest tests on real, committing connections."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.agent_credentials import AgentContext
from app.core.errors import AppError
from app.models.config import CompanySetting
from app.models.enums import CollectionType, SettingDataType, SyncMode
from app.models.sync import SyncWatermark
from app.sync import leases
from app.sync.ingest import BatchResult, ingest
from tally_contract.records import AlterIdWindow, BatchEnvelope, DateWindow
from tests.factories import (
    agent_context,
    make_company,
    make_registered_agent,
    make_running_command,
    make_sync_run,
)

Factory = async_sessionmaker[AsyncSession]
GUID = "guid-test-co"


@dataclass
class Setup:
    company_id: uuid.UUID
    agent: AgentContext
    command_id: uuid.UUID
    run_id: uuid.UUID
    company_guid: str = GUID


async def setup(
    committed: Factory,
    *,
    sync_mode: SyncMode = SyncMode.FULL,
    books_from: date | None = date(2024, 4, 1),
    chunk_size: int | None = None,
    name: str = "Head Office",
    company_id: uuid.UUID | None = None,
    guid: str | None = None,
    dates: tuple[date, date] | None = None,
) -> Setup:
    """A company (new, or `company_id`), an Agent with a RUNNING command and an open run.
    Each new company gets its own Tally GUID (they are unique across companies)."""
    async with committed() as s:
        if company_id is None:
            company = await make_company(s, tally_guid=guid or f"guid-{uuid.uuid4()}")
            company.books_from = books_from
            company_id = company.company_id
            if chunk_size is not None:
                s.add(
                    CompanySetting(
                        company_id=company_id,
                        setting_key="sync.db_commit_batch",
                        setting_value=chunk_size,
                        data_type=SettingDataType.INTEGER,
                    )
                )
        from app.models.company import Company

        company = await s.get(Company, company_id)
        assert company is not None and company.tally_guid is not None
        agent, _ = await make_registered_agent(s, company, name)
        extra = {"date_from": dates[0], "date_to": dates[1]} if dates else {}
        command = await make_running_command(s, agent, sync_mode, **extra)
        run = await make_sync_run(s, command)
        await s.commit()
    return Setup(
        company_id, agent_context(agent), command.command_id, run.sync_run_id, company.tally_guid
    )


async def end_run(committed: Factory, st: Setup) -> None:
    """The run is over: its Agent's leases are released for the next run."""
    async with committed() as s:
        await leases.release_all(s, st.company_id, st.agent.agent_id)
        await s.commit()


async def lease(committed: Factory, st: Setup, collection: CollectionType) -> None:
    async with committed() as s:
        await leases.acquire(s, st.agent, collection, datetime.now(UTC))
        await s.commit()


def envelope(
    st: Setup,
    collection: CollectionType,
    records: list[Any],
    *,
    window: AlterIdWindow | DateWindow | None = None,
    parse_errors: list[Any] | None = None,
    batch_id: uuid.UUID | None = None,
) -> BatchEnvelope:
    if window is None and records:
        window = AlterIdWindow(from_alter_id=0, to_alter_id=max(r.alter_id for r in records))
    return BatchEnvelope(
        collection_type=collection,
        command_id=st.command_id,
        sync_run_id=st.run_id,
        batch_seq=0,
        batch_id=batch_id or uuid.uuid4(),
        window=window,
        records=sorted(records, key=lambda r: r.alter_id),
        parse_errors=parse_errors or [],
    )


async def upload(committed: Factory, st: Setup, env: BatchEnvelope) -> BatchResult | str:
    async with committed() as s:
        try:
            return await ingest(s, st.agent, st.command_id, env)
        except AppError as exc:
            return exc.code.value


async def watermark(committed: Factory, company_id: uuid.UUID, collection: CollectionType) -> int:
    async with committed() as s:
        value = await s.scalar(
            select(SyncWatermark.last_alter_id).where(
                SyncWatermark.company_id == company_id, SyncWatermark.collection_type == collection
            )
        )
        return int(value or 0)


async def count(committed: Factory, model: Any, company_id: uuid.UUID) -> int:
    async with committed() as s:
        return int(
            await s.scalar(
                select(func.count()).select_from(model).where(model.company_id == company_id)
            )
            or 0
        )


# --- a small, consistent dataset ------------------------------------------------------------


def _amount(raw: str, deemed_positive: bool) -> Any:
    from tally_contract import normalize

    return normalize.to_amount(raw, deemed_positive)


MASTERS: dict[CollectionType, list[Any]] = {}


def masters() -> dict[CollectionType, list[Any]]:
    from tally_contract.records import (
        CostCentreRecord,
        GroupRecord,
        LedgerRecord,
        StockItemRecord,
        VoucherTypeRecord,
    )

    def led(guid: str, alter: int, name: str, parent: str) -> LedgerRecord:
        return LedgerRecord(
            guid=guid, alter_id=alter, name=name, parent_group_guid=parent, parent_group_name=parent
        )

    return {
        CollectionType.GROUP: [
            GroupRecord(
                guid="g-sales", alter_id=1, name="Sales Accounts", reserved_name="Sales Accounts"
            ),
            GroupRecord(
                guid="g-sd", alter_id=2, name="Sundry Debtors", reserved_name="Sundry Debtors"
            ),
            GroupRecord(
                guid="g-cash", alter_id=3, name="Cash-in-Hand", reserved_name="Cash-in-Hand"
            ),
            GroupRecord(
                guid="g-tax", alter_id=4, name="Duties & Taxes", reserved_name="Duties & Taxes"
            ),
        ],
        CollectionType.LEDGER: [
            led("l-cash", 10, "Cash", "g-cash"),
            led("l-sales", 11, "Sales - Retail", "g-sales"),
            led("l-sharma", 12, "Sharma Traders", "g-sd"),
            led("l-ogst", 13, "Output GST", "g-tax"),
        ],
        CollectionType.VOUCHER_TYPE: [
            VoucherTypeRecord(guid="vt-sales", alter_id=20, name="Sales", reserved_name="Sales"),
            VoucherTypeRecord(guid="vt-rcpt", alter_id=21, name="Receipt", reserved_name="Receipt"),
        ],
        CollectionType.STOCK_ITEM: [
            StockItemRecord(guid="s-soap", alter_id=30, name="Soap", base_unit="Nos")
        ],
        CollectionType.COST_CENTRE: [
            CostCentreRecord(guid="cc-retail", alter_id=40, name="Retail")
        ],
    }


def sale(
    guid: str,
    alter: int,
    total: str,
    *,
    number: str = "S-1",
    when: date = date(2024, 4, 1),
    customer: tuple[str | None, str] = ("l-sharma", "Sharma Traders"),
    cancelled: bool = False,
    with_bill: bool = True,
    with_item: bool = True,
) -> Any:
    """A balanced sale: customer debit = sales credit + 18% GST credit."""
    from decimal import Decimal

    from tally_contract.enums import AllocationType
    from tally_contract.records import (
        BillAllocation,
        CostCentreAllocation,
        InventoryEntry,
        LedgerEntry,
        VoucherRecord,
    )

    gross = Decimal(total)
    net = (gross / Decimal("1.18")).quantize(Decimal("0.01"))
    tax = gross - net
    entries = [
        LedgerEntry(
            ledger_guid=customer[0],
            ledger_name=customer[1],
            line_sequence=1,
            amount=_amount(f"-{gross}", True),
            bill_allocations=[
                BillAllocation(
                    reference_name=number,
                    allocation_type_raw="New Ref",
                    allocation_type=AllocationType.NEW_REF,
                    amount=_amount(f"-{gross}", True),
                )
            ]
            if with_bill
            else [],
        ),
        LedgerEntry(
            ledger_guid="l-sales",
            ledger_name="Sales - Retail",
            line_sequence=2,
            amount=_amount(str(net), False),
            cost_centre_allocations=[
                CostCentreAllocation(
                    cost_centre_guid="cc-retail", cost_centre_name="Retail", amount_absolute=net
                )
            ],
        ),
        LedgerEntry(
            ledger_guid="l-ogst",
            ledger_name="Output GST",
            line_sequence=3,
            amount=_amount(str(tax), False),
        ),
    ]
    items = (
        [
            InventoryEntry(
                stock_item_guid="s-soap",
                stock_item_name="Soap",
                line_sequence=1,
                quantity=Decimal(10),
                unit="Nos",
                rate=net / 10,
                amount=_amount(str(net), False),
            )
        ]
        if with_item
        else []
    )
    return VoucherRecord(
        guid=guid,
        alter_id=alter,
        voucher_number=number,
        voucher_type_guid="vt-sales",
        voucher_type_name="Sales",
        voucher_date=when,
        is_cancelled=cancelled,
        entries=entries,
        items=items,
    )


async def sync_masters(
    committed: Factory, st: Setup, data: dict[CollectionType, list[Any]] | None = None
) -> None:
    for collection, records in (data or masters()).items():
        await lease(committed, st, collection)
        result = await upload(committed, st, envelope(st, collection, records))
        assert isinstance(result, BatchResult) and result.failed == 0, (collection, result)
