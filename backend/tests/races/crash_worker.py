"""Subprocess for the crash tests (TEST-3.3): ingests one batch and pauses forever at a chosen
voucher, just after its entries are written and before its allocations, so the parent can
SIGKILL it there. Run as: python -m tests.races.crash_worker <spec.json>"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import time_machine

from app.core.agent_credentials import AgentContext
from app.core.db import session_factory
from app.models.enums import AgentStatus
from app.sync import vouchers
from app.sync.ingest import ingest
from tally_contract.records import BatchEnvelope


async def main(spec_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    real = vouchers._insert_allocations
    seen = 0

    async def pause_at(*args: Any, **kwargs: Any) -> None:
        nonlocal seen
        seen += 1
        if seen == spec["pause_at_voucher"]:
            Path(spec["marker"]).write_text("paused", encoding="utf-8")
            await asyncio.sleep(3600)  # killed here
        await real(*args, **kwargs)

    vouchers._insert_allocations = pause_at  # type: ignore[assignment]
    agent = AgentContext(
        uuid.UUID(spec["agent_id"]), uuid.UUID(spec["company_id"]), AgentStatus.ACTIVE
    )
    env = BatchEnvelope.model_validate_json(spec["envelope"])
    # The parent test runs on the fixed test clock (CLAUDE.md); so does this process.
    with time_machine.travel(datetime.fromisoformat(spec["now"]), tick=True):
        async with session_factory()() as session:
            await ingest(session, agent, uuid.UUID(spec["command_id"]), env)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
