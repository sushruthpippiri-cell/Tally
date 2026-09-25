from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    agent_protocol,
    agents,
    auth,
    commands,
    companies,
    health,
    schedules,
    users,
)
from app.api import settings as settings_api
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import install_middleware
from tally_contract.log import configure_logging, get_logger


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or get_settings()
    configure_logging(config.env)

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
    ):
        app.include_router(module.router)
    get_logger(__name__).info("app_started", env=config.env)
    return app
