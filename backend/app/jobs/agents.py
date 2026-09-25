"""Agent jobs: offline detection (SRS 4.5)."""

from datetime import datetime
from typing import Any

from sqlalchemy import Integer, Text, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.settings_registry import SETTINGS
from app.models.agents import Agent
from app.models.config import CompanySetting
from app.models.enums import AgentStatus
from tally_contract.log import get_logger

log = get_logger(__name__)


def company_int_setting(company_id: Any, key: str) -> ColumnElement[int]:
    """SQL for a company's integer setting: its override, else the registry default."""
    override = (
        select(CompanySetting.setting_value.cast(Text).cast(Integer))  # jsonb 5 -> '5' -> 5
        .where(CompanySetting.company_id == company_id, CompanySetting.setting_key == key)
        .scalar_subquery()
    )
    return func.coalesce(override, SETTINGS[key].default)


async def mark_offline(session: AsyncSession, now: datetime) -> int:
    """ACTIVE Agents silent for longer than their company's agent.offline_threshold_minutes
    become OFFLINE. Heartbeats lock the same row, so the two never interleave."""
    threshold = company_int_setting(Agent.company_id, "agent.offline_threshold_minutes")
    rows = await session.execute(
        update(Agent)
        .where(
            Agent.status == AgentStatus.ACTIVE,
            Agent.last_heartbeat_at < now - func.make_interval(0, 0, 0, 0, 0, threshold),
        )
        .values(status=AgentStatus.OFFLINE)
        .returning(Agent.agent_id, Agent.company_id, Agent.last_heartbeat_at)
    )
    changed = rows.all()
    for agent_id, company_id, last in changed:
        log.info(
            "agent_offline",
            agent_id=str(agent_id),
            company_id=str(company_id),
            last_heartbeat_at=last.isoformat() if last else None,
        )
    return len(changed)
