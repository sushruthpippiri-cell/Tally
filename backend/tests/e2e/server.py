"""The backend for the end-to-end tests: a real uvicorn server in its own process, on the
test's clock (CLAUDE.md: tests never depend on the real date), so tokens and leases the test
writes mean the same to it. Run as: python -m tests.e2e.server <port> <iso-now>"""

import sys
from datetime import datetime

import time_machine
import uvicorn


def main() -> None:
    port, now = int(sys.argv[1]), datetime.fromisoformat(sys.argv[2])
    with time_machine.travel(now, tick=True):
        uvicorn.run(
            "app.main:create_app", factory=True, host="127.0.0.1", port=port, log_level="warning"
        )


if __name__ == "__main__":
    main()
