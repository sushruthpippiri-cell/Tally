"""P1.3: agents, registration tokens, commands and schedules (SRS 5.4, D-025)."""

from datetime import date

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import AgentCommand, SyncSchedule
from app.models.enums import SyncMode
from tests.factories import db_error, make_agent, make_command, make_company


async def test_agent_name_unique_per_company(session: AsyncSession) -> None:
    a, b = await make_company(session), await make_company(session)
    await make_agent(session, a, "front-office")
    await make_agent(session, b, "front-office")  # other company: fine
    async with db_error(session, "uq_agents_company_id_agent_name"):
        await make_agent(session, a, "front-office")


@pytest.mark.req("RTE-1.4")
@pytest.mark.parametrize("column", ["agent_id", "company_id"])
async def test_command_owner_is_immutable(session: AsyncSession, column: str) -> None:
    company = await make_company(session)
    agent, other = await make_agent(session, company, "a"), await make_agent(session, company, "b")
    command = await make_command(session, agent)
    new_value = other.agent_id if column == "agent_id" else (await make_company(session)).company_id
    async with db_error(session, "RTE-1.4"):
        await session.execute(
            update(AgentCommand)
            .where(AgentCommand.command_id == command.command_id)
            .values({column: new_value})
        )


async def test_command_other_columns_are_updatable(session: AsyncSession) -> None:
    command = await make_command(session, await make_agent(session, await make_company(session)))
    await session.execute(
        update(AgentCommand)
        .where(AgentCommand.command_id == command.command_id)
        .values(status="CLAIMED")
    )


@pytest.mark.req("RTE-1.4")
async def test_command_agent_is_mandatory(session: AsyncSession) -> None:
    company = await make_company(session)
    async with db_error(session, "agent_id"):
        await session.execute(
            text(
                "INSERT INTO agent_commands (company_id, command_type, sync_mode, status) "
                "VALUES (:c, 'RUN_SYNC', 'FULL', 'PENDING')"
            ),
            {"c": company.company_id},
        )


async def test_command_cannot_target_another_companys_agent(session: AsyncSession) -> None:
    agent = await make_agent(session, await make_company(session))
    other = await make_company(session)
    async with db_error(session, "fk_agent_commands_company_id_agent_id"):
        session.add(
            AgentCommand(
                company_id=other.company_id,
                agent_id=agent.agent_id,
                command_type="RUN_SYNC",
                sync_mode="FULL",
                status="PENDING",
            )
        )
        await session.flush()


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [(None, None), (date(2024, 4, 1), None), (date(2024, 5, 1), date(2024, 4, 1))],
)
async def test_date_range_needs_ordered_dates(
    session: AsyncSession, date_from: date | None, date_to: date | None
) -> None:
    agent = await make_agent(session, await make_company(session))
    async with db_error(session, "ck_agent_commands_date_range"):
        session.add(
            AgentCommand(
                company_id=agent.company_id,
                agent_id=agent.agent_id,
                command_type="RUN_SYNC",
                sync_mode=SyncMode.DATE_RANGE,
                status="PENDING",
                date_from=date_from,
                date_to=date_to,
            )
        )
        await session.flush()


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("agents", "status"),
        ("agents", "last_tally_status"),
        ("agent_commands", "status"),
        ("agent_commands", "sync_mode"),
        ("agent_commands", "command_type"),
        ("sync_schedules", "sync_mode"),
    ],
)
async def test_unknown_enum_values_rejected(session: AsyncSession, table: str, column: str) -> None:
    agent = await make_agent(session, await make_company(session))
    command = await make_command(session, agent)
    session.add(
        SyncSchedule(
            company_id=agent.company_id,
            agent_id=agent.agent_id,
            cron_expression="0 * * * *",
            sync_mode="INCREMENTAL",
        )
    )
    await session.flush()
    key = {"agents": "agent_id", "agent_commands": "command_id", "sync_schedules": "agent_id"}
    key_value = command.command_id if table == "agent_commands" else agent.agent_id
    async with db_error(session, f"ck_{table}_{column}"):
        await session.execute(
            text(f"UPDATE {table} SET {column} = 'BOGUS' WHERE {key[table]} = :k"),
            {"k": key_value},
        )
