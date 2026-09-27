"""Logs: to stderr, and to rotating files in <data_dir>/logs when running as a service."""

import logging
import logging.handlers
from pathlib import Path

from tally_agent import security
from tally_contract.log import configure_logging


def setup(data_dir: Path | None, service_account: str, env: str = "prod") -> None:
    configure_logging(env)
    if data_dir is None:
        return
    logs = security.private_dir(data_dir / "logs", service_account)
    root = logging.getLogger()
    handler = logging.handlers.RotatingFileHandler(
        logs / "agent.log", maxBytes=10_000_000, backupCount=10, encoding="utf-8"
    )
    if root.handlers:
        handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)
