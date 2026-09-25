from fastapi import FastAPI

from app.api import auth, companies, health
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from tally_contract.log import configure_logging, get_logger


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.env)
    app = FastAPI(title="Tally Analytics Platform")
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(companies.router)
    get_logger(__name__).info("app_started", env=settings.env)
    return app
