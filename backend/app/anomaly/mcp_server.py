"""The anomaly MCP server (FR-3.5, SEC-1.12, SRS 19.3, D-055 #5).

Exactly one read-only tool, `get_anomaly_evidence(anomaly_id)`, returning the redacted evidence
for that one anomaly. No bulk data, no arbitrary SQL, and nothing it returns has ever been typed
by a person (see `redact`).

Four things make the boundary real rather than promised:

* **The company is fixed at spawn**, from `ANOMALY_COMPANY_ID`. The model supplies only an
  anomaly id, so it cannot ask about another company.
* **The role is `tally_readonly`**: `SELECT` on `anomaly_flags` and nothing else, anywhere. It
  cannot write, so the explainer - not this server - records the call in `ai_tool_log` (FR-3.9).
* **Row-level security** keyed on `app.company_id`, set once per connection from that
  environment variable. Even a bug in the query below cannot return another company's evidence.
* **Credentials arrive in the environment**, never on the command line, where `ps` would show
  them to every user on the machine.

Run as `python -m app.anomaly.mcp_server`. Tests drive the same `build()` server in process.
"""

import os
import uuid
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.anomaly.redact import evidence
from app.models.config import AnomalyFlag

TOOL = "get_anomaly_evidence"
NOT_FOUND = "No such anomaly for this company."
COMPANY_ENV = "ANOMALY_COMPANY_ID"
DSN_ENV = "ANOMALY_READONLY_DATABASE_URL"


def _async_url(dsn: str) -> str:
    """The read-only DSN is a libpq URL (it is also handed to psql by hand); this server talks
    to it through SQLAlchemy's asyncpg dialect."""
    url = make_url(dsn)
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


async def fetch(session: AsyncSession, company_id: uuid.UUID, anomaly_id: int) -> dict[str, Any]:
    """The whole of what this server can do. `set_config` scopes the row-level security policy
    to the company fixed at spawn; `SET` would not take a bind parameter."""
    await session.execute(
        text("SELECT set_config('app.company_id', :c, false)"), {"c": str(company_id)}
    )
    flag = (
        await session.execute(
            select(AnomalyFlag).where(
                AnomalyFlag.id == anomaly_id,
                # Belt as well as braces: the policy already restricts this, and a test proves
                # the policy alone is enough.
                AnomalyFlag.company_id == company_id,
                AnomalyFlag.cleared_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if flag is None:
        # ToolError is the SDK's "anticipated failure": its message reaches the model. Anything
        # else is treated as a crash and masked, which is what we want for a real bug.
        raise ToolError(NOT_FOUND)
    return evidence(
        rule=flag.rule_triggered,
        transaction_amount=flag.transaction_amount,
        historical_average=flag.historical_average,
        historical_max=flag.historical_max,
        deviation_percent=flag.deviation_percent,
        has_duplicate=flag.duplicate_of_voucher_id is not None,
    )


def build(sessions: async_sessionmaker[AsyncSession], company_id: uuid.UUID) -> MCPServer:
    """The server, with its one tool bound to one company."""
    server: MCPServer = MCPServer(
        name="tally-anomaly-evidence",
        instructions=(
            "Read the stored evidence for one anomaly. There is no other data here, and no way "
            "to ask for more than one anomaly at a time."
        ),
    )

    @server.tool(
        name=TOOL,
        description=(
            "The stored numeric evidence for one anomaly: the transaction amount, the party's "
            "historical average and maximum, the deviation percentage, and which rule flagged "
            "it. Parties and vouchers are referred to by placeholder labels."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    async def get_anomaly_evidence(anomaly_id: int) -> dict[str, Any]:
        async with sessions() as session:
            return await fetch(session, company_id, anomaly_id)

    return server


def main() -> None:  # pragma: no cover - the subprocess entry point
    company = os.environ[COMPANY_ENV]
    engine = create_async_engine(_async_url(os.environ[DSN_ENV]))
    server = build(async_sessionmaker(engine, expire_on_commit=False), uuid.UUID(company))
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
