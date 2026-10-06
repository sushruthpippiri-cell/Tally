"""Settings from environment variables (see .env.example)."""

from functools import lru_cache
from ipaddress import ip_network
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEV_DATABASE_URL = "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally"
_DEV_MIGRATION_URL = "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally"
_DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-in-prod"  # >= 32 bytes for HS256
# The anomaly MCP server's own connection (P15, D-055 #5): a libpq DSN, not a SQLAlchemy URL,
# because the server connects directly. SELECT on anomaly_flags only, scoped to one company by
# row-level security.
_DEV_READONLY_URL = "postgresql://tally_readonly:tally_readonly_dev@localhost:5432/tally"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str | None = None  # app role (DML only)
    database_migration_url: str | None = None  # owner role (DDL), Alembic only
    jwt_secret: SecretStr | None = None
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_hours: int = 24
    # D-051 #1: the refresh cookie is sent only to the auth endpoints, as the browser sees them
    # (the app's /api prefix is stripped by the proxy before the backend).
    refresh_cookie_path: str = "/api/auth"
    cors_origins: Annotated[list[str], NoDecode] = []
    # D-033 #5-6: X-Forwarded-For/-Proto are honoured only from these peers (CIDRs).
    trusted_proxies: Annotated[list[str], NoDecode] = []
    # D-043: each verified Agent has its own bucket (SEC-1.9's user limit); the window is a
    # setting only so tests can shrink it.
    agent_rate_limit: int = 1000
    rate_limit_window_seconds: int = 60
    min_agent_version: str = "0.0.0"
    min_tdl_version: str = "0.0.0"
    allow_unverified_incremental: bool | None = None  # D-029: true in dev/test, false in prod
    scheduler_enabled: bool = True  # background jobs (app/jobs); off in tests
    # D-053 #7a, as the owner amended it: the PDF limit protects the *server*, so it is one
    # per-process cap from configuration, not a company setting - ten companies must not be
    # able to render twenty PDFs at once, and no company can raise its own limit.
    pdf_max_concurrent: int = 2
    # SRS 15 / D-056 #4: one retention period for the sync and AI tool logs, not a company
    # setting - how long operational logs are kept is the operator's decision, not a tenant's.
    # SRS 15 asks for at least 90 days; the owner chose 180. `audit_logs` is never purged
    # (SEC-1.13: the app role cannot delete, and a trigger refuses it for everyone).
    log_retention_days: int = 180
    # P15, all three optional: with any of them unset, anomalies are still found and shown with
    # their evidence and the explanation reads "unavailable" (AC-58, NFR-REL-1). Never literals in
    # code (SEC-1.14).
    anthropic_api_key: SecretStr | None = None
    anomaly_explainer_model: str | None = None
    anomaly_readonly_database_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _split_cors(cls, data: dict[str, object]) -> dict[str, object]:
        for key in ("cors_origins", "trusted_proxies"):
            raw = data.get(key)
            if isinstance(raw, str):
                data[key] = [o.strip() for o in raw.split(",") if o.strip()]
        return data

    @field_validator("log_retention_days")
    @classmethod
    def _at_least_the_srs_minimum(cls, value: int) -> int:
        if value < 90:
            raise ValueError("log_retention_days must be at least 90 (SRS 15)")
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _cidrs(cls, value: list[str]) -> list[str]:
        for cidr in value:
            ip_network(cidr, strict=False)  # ValueError -> startup fails with the bad entry
        return value

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
            assert self.jwt_secret is not None
            if len(self.jwt_secret.get_secret_value().encode()) < 32:
                raise ValueError("JWT_SECRET must be at least 32 bytes (HS256)")
            if self.allow_unverified_incremental is None:
                self.allow_unverified_incremental = False
        else:
            self.database_url = self.database_url or _DEV_DATABASE_URL
            self.database_migration_url = self.database_migration_url or _DEV_MIGRATION_URL
            self.jwt_secret = self.jwt_secret or SecretStr(_DEV_JWT_SECRET)
            self.anomaly_readonly_database_url = (
                self.anomaly_readonly_database_url or _DEV_READONLY_URL
            )
            if self.allow_unverified_incremental is None:
                self.allow_unverified_incremental = True
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
