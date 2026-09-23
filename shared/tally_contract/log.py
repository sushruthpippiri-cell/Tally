"""Structured logging shared by the backend, the Agent and the contract package.

structlog sits on top of stdlib `logging`, so pytest's `caplog` sees every record;
`record.msg` is the event dict (`event`, `level`, bound context, keyword fields).
Bind request-scoped context (request_id, company_id, agent_id) with
`structlog.contextvars.bind_contextvars(...)`.
"""

import logging
import sys

import structlog
from structlog.stdlib import BoundLogger, ProcessorFormatter

_SHARED: list[structlog.typing.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def configure_logging(env: str = "dev", level: str | None = None) -> None:
    """env: dev | test | prod. In `test` pytest owns the handlers, so none is installed."""
    structlog.configure(
        processors=[*_SHARED, ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=BoundLogger,
        cache_logger_on_first_use=False,
    )
    if env == "test":
        return
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if env == "prod" else structlog.dev.ConsoleRenderer()
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        ProcessorFormatter(
            foreign_pre_chain=_SHARED,
            processors=[ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level or ("INFO" if env == "prod" else "DEBUG"))


def get_logger(name: str | None = None) -> BoundLogger:
    return structlog.stdlib.get_logger(name)
