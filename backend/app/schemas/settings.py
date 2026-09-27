from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from tally_contract.udf import UdfMapping


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


class CustomFieldsUpdate(BaseModel):
    """The complete list of mappings (DR-UDF-1); a mapping left out is switched off."""

    model_config = ConfigDict(extra="forbid")
    mappings: list[UdfMapping] = Field(max_length=200)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        keys = [(m.collection_type, m.field_key) for m in self.mappings]
        if len(set(keys)) != len(keys):
            raise ValueError("a field_key is mapped twice for the same collection")
        return self
