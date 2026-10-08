"""The backend for the end-to-end tests: a real uvicorn server in its own process, on the
test's clock (CLAUDE.md: tests never depend on the real date), so tokens and leases the test
writes mean the same to it. Run as: python -m tests.e2e.server <port> <iso-now>"""

import os
import sys
from datetime import datetime
from typing import Any

import time_machine
import uvicorn

# Set by the log-redaction test only. Adds a route that lets a real database error escape the
# handlers, so what uvicorn writes for an *unhandled* exception can be examined. It lives here,
# in test code, rather than in the application.
LEAK_ROUTE = "E2E_UNHANDLED_DB_ERROR_ROUTE"


def factory() -> Any:
    from app.main import create_app

    app = create_app()
    planted = os.environ.get(LEAK_ROUTE)
    if planted:
        from fastapi import Depends
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.db import get_session

        @app.get("/e2e/unhandled-db-error")
        async def _unhandled(session: AsyncSession = Depends(get_session)) -> None:
            # A real check-constraint violation, so PostgreSQL's DETAIL line is genuine and
            # carries the planted value. Nothing catches it: it reaches uvicorn.
            await session.execute(
                text(
                    "INSERT INTO ai_tool_log (company_id, tool_name, status, result_summary,"
                    " created_at) VALUES (gen_random_uuid(), 'get_anomaly_evidence',"
                    " 'NOT_A_STATUS', :planted, now())"
                ),
                {"planted": planted},
            )

    return app


def main() -> None:
    port, now = int(sys.argv[1]), datetime.fromisoformat(sys.argv[2])
    with time_machine.travel(now, tick=True):
        uvicorn.run(factory, factory=True, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
