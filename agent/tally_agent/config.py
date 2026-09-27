"""The Agent's local configuration, `<data_dir>/agent.toml` (P7.1, D-042 #4).

It holds no secret (the credential lives in the secret store) and no setting can weaken TLS:
the model is strict, so an unknown key such as `verify` is refused.
"""

import ipaddress
import os
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

SERVICE_ACCOUNT = r"NT SERVICE\TallyAgent"  # the service's virtual account (D-042 #3)


def default_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "TallyAgent"
    return Path.home() / ".tally-agent"


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backend_url: str
    company_name: str = Field(min_length=1)  # the Tally company to register with
    tally_host: str = "localhost"
    tally_port: int = Field(default=9000, ge=1, le=65535)
    data_dir: Path = Field(default_factory=default_data_dir)
    service_account: str = SERVICE_ACCOUNT
    proxy_url: str | None = None  # credentials, if any, via `set-proxy-credentials`
    ca_bundle: Path | None = None  # extra CA certificates (PEM), trusted besides certifi's
    tally_timeout_seconds: float = Field(default=600, gt=0)  # AGT-4.3
    tally_process_name: str = "tally.exe"
    upload_batch_records: int = Field(default=500, ge=1, le=5000)

    @field_validator("backend_url")
    @classmethod
    def _https(cls, value: str) -> str:
        """SEC-2.0: HTTPS only; plain HTTP only to this machine (tests, development)."""
        parts = urlsplit(value)
        if parts.username or parts.password:
            raise ValueError("backend_url must not contain credentials")
        if parts.scheme == "https" or (
            parts.scheme == "http" and is_loopback(parts.hostname or "")
        ):
            return value.rstrip("/")
        raise ValueError("backend_url must use https://")

    @field_validator("proxy_url")
    @classmethod
    def _proxy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("proxy_url must be http://host:port or https://host:port")
        if parts.username or parts.password:
            raise ValueError(
                "proxy credentials go in the secret store: tally-agent set-proxy-credentials"
            )
        return value

    @field_validator("ca_bundle")
    @classmethod
    def _bundle(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_file():
            raise ValueError(f"ca_bundle {value} does not exist")
        return value


def config_path(data_dir: Path) -> Path:
    return data_dir / "agent.toml"


def load(path: Path) -> AgentSettings:
    with path.open("rb") as f:
        return AgentSettings.model_validate(tomllib.load(f))


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def save(settings: AgentSettings) -> Path:
    """Writes the non-default settings; the installer or `register` calls this once."""
    path = config_path(settings.data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = settings.model_dump(exclude_defaults=True) | {"data_dir": settings.data_dir}
    lines = [f"{key} = {_toml(value)}" for key, value in values.items() if value is not None]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path
