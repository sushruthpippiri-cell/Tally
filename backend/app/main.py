from fastapi import FastAPI

from app.api import auth, companies, health, users
from app.api import settings as settings_api
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import install_middleware
from tally_contract.log import configure_logging, get_logger


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or get_settings()
    configure_logging(config.env)
    app = FastAPI(title="Tally Analytics Platform")
    install_error_handlers(app)
    install_middleware(app, config)
    for module in (health, auth, companies, users, settings_api):
        app.include_router(module.router)
    get_logger(__name__).info("app_started", env=config.env)
    return app
