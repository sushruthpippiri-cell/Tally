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


async def setup(
    committed: Factory,
    *,
    sync_mode: SyncMode = SyncMode.FULL,
    books_from: date | None = date(2024, 4, 1),
    chunk_size: int | None = None,
    name: str = "Head Office",
    company_id: uuid.UUID | None = None,
) -> Setup:
    async with committed() as s:
        if company_id is None:
            company = await make_company(s, tally_guid=GUID)
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
        assert company is not None
        agent, _ = await make_registered_agent(s, company, name)
        command = await make_running_command(s, agent, sync_mode)
        run = await make_sync_run(s, command)
        await s.commit()
    return Setup(company_id, agent_context(agent), command.command_id, run.sync_run_id)


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
