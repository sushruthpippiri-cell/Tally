from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    agent_protocol,
    agents,
    analytics,
    anomalies,
    auth,
    commands,
    companies,
    data_quality,
    exports,
    health,
    masters,
    reconciliation,
    schedules,
    sync,
    users,
    vouchers,
)
from app.api import settings as settings_api
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.log_redaction import install as install_log_redaction
from app.core.middleware import install_middleware
from tally_contract.log import configure_logging, get_logger


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or get_settings()
    configure_logging(config.env)
    # Before anything can format a traceback: an unhandled database error carries
    # PostgreSQL's DETAIL (the whole failing row) and SQLAlchemy's bound parameters, and
    # the server re-raises it after the 500 so it can log exactly that (P16.5).
    install_log_redaction()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler = None
        if config.scheduler_enabled:
            from app.jobs.runner import build_scheduler

            scheduler = build_scheduler()
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Tally Analytics Platform", lifespan=lifespan)
    install_error_handlers(app)
    install_middleware(app, config)
    for module in (
        health,
        auth,
        companies,
        users,
        settings_api,
        agents,
        agent_protocol,
        commands,
        schedules,
        sync,
        data_quality,
        masters,
        analytics,
        anomalies,
        exports,
        reconciliation,
        vouchers,
    ):
        app.include_router(module.router)
    get_logger(__name__).info("app_started", env=config.env)
    return app
