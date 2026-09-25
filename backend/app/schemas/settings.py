from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool


class SettingValue(BaseModel):
    value: Any
    is_default: bool


class FlagValue(BaseModel):
    enabled: bool
    is_default: bool


class SettingsOut(BaseModel):
    settings: dict[str, SettingValue]
    feature_flags: dict[str, FlagValue]


class SettingsUpdate(BaseModel):
    """Partial update; values are validated against app/core/settings_registry.py."""

    model_config = ConfigDict(extra="forbid")
    settings: dict[str, Any] = {}
    feature_flags: dict[str, StrictBool] = {}  # SRS 18.1: boolean only
