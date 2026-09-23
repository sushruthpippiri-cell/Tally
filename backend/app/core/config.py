"""Settings from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEV_DATABASE_URL = "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally"
_DEV_MIGRATION_URL = "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally"
_DEV_JWT_SECRET = "dev-only-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str | None = None  # app role (DML only)
    database_migration_url: str | None = None  # owner role (DDL), Alembic only
    jwt_secret: SecretStr | None = None
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_hours: int = 24
    cors_origins: Annotated[list[str], NoDecode] = []
    min_agent_version: str = "0.0.0"
    min_tdl_version: str = "0.0.0"
    allow_unverified_incremental: bool | None = None  # D-029: true in dev/test, false in prod
    anthropic_api_key: SecretStr | None = None
    anomaly_explainer_model: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _split_cors(cls, data: dict[str, object]) -> dict[str, object]:
        raw = data.get("cors_origins")
        if isinstance(raw, str):
            data["cors_origins"] = [o.strip() for o in raw.split(",") if o.strip()]
        return data

    @model_validator(mode="after")
    def _apply_env_defaults(self) -> "Settings":
        if self.env == "prod":
            # SEC-1.14: secrets and connection strings come from the environment, never defaults.
            missing = [
                name.upper()
                for name in ("database_url", "database_migration_url", "jwt_secret", "cors_origins")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(f"missing required settings in prod: {', '.join(missing)}")
            if self.allow_unverified_incremental is None:
                self.allow_unverified_incremental = False
        else:
            self.database_url = self.database_url or _DEV_DATABASE_URL
            self.database_migration_url = self.database_migration_url or _DEV_MIGRATION_URL
            self.jwt_secret = self.jwt_secret or SecretStr(_DEV_JWT_SECRET)
            if self.allow_unverified_incremental is None:
                self.allow_unverified_incremental = True
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
