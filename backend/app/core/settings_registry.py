"""Every company setting (SRS 18.2 plus D-016/D-033 additions): type, default, validator.

Values are stored in company_settings as JSON: decimals as strings (never float, CLAUDE.md
rule 10). Validators take the JSON value from the API and return the value to store, or raise
ValueError. Classification allow-lists are checked here for shape only; whether a
COMPANY_GROUP entry names one of the company's own top-level groups needs the database and is
checked in app/services/settings.py (D-001).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from app.models.defaults import DEFAULT_CLASSIFICATION_ALLOW_LISTS, PREDEFINED_GROUP_NAMES
from app.models.enums import SettingDataType

Validator = Callable[[Any], Any]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    data_type: SettingDataType
    default: Any  # stored (JSON) form
    validate: Validator


def _int(lo: int, hi: int | None = None) -> Validator:
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be a whole number")
        if value < lo or (hi is not None and value > hi):
            raise ValueError(f"must be between {lo} and {hi}" if hi else f"must be >= {lo}")
        return value

    return check


def _decimal(
    *, positive: bool = False, at_most: str | None = None, nullable: bool = False
) -> Validator:
    def check(value: Any) -> str | None:
        if value is None and nullable:
            return None
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValueError('must be a decimal number sent as a string, e.g. "0.5"')
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("must be a decimal number") from exc
        if not number.is_finite():
            raise ValueError("must be a finite number")
        if number < 0 or (positive and number == 0):
            raise ValueError("must be greater than 0" if positive else "must be >= 0")
        if at_most is not None and number > Decimal(at_most):
            raise ValueError(f"must be at most {at_most}")
        return str(number)

    return check


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def _choice(*options: str) -> Validator:
    def check(value: Any) -> str:
        if value not in options:
            raise ValueError(f"must be one of: {', '.join(options)}")
        return str(value)

    return check


def _bucket_boundaries(value: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError("must be a non-empty list of days")
    days = [_int(1)(v) for v in value]
    if any(a >= b for a, b in zip(days, days[1:], strict=False)):
        raise ValueError("must be strictly ascending")
    return days


class PredefinedEntry(BaseModel):
    """One of Tally's 28 predefined groups, by reserved name (D-001, G32)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["PREDEFINED"]
    reserved_name: str

    @field_validator("reserved_name")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in PREDEFINED_GROUP_NAMES:
            raise ValueError(f"{value!r} is not one of Tally's predefined groups")
        return value


class CompanyGroupEntry(BaseModel):
    """One of the company's own top-level groups, by GUID (D-001, DR-4.2)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["COMPANY_GROUP"]
    tally_guid: str = Field(min_length=1)


AllowListEntry = Annotated[PredefinedEntry | CompanyGroupEntry, Field(discriminator="type")]
_ALLOW_LIST: TypeAdapter[list[AllowListEntry]] = TypeAdapter(list[AllowListEntry])


def parse_allow_list(value: Any) -> list[PredefinedEntry | CompanyGroupEntry]:
    if not isinstance(value, list) or not value:
        raise ValueError("must be a non-empty list of group entries")
    try:
        entries = _ALLOW_LIST.validate_python(value)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValueError(
            'each entry must be {"type": "PREDEFINED", "reserved_name": ...} or '
            f'{{"type": "COMPANY_GROUP", "tally_guid": ...}}, never a display name '
            f"({first['msg']})"
        ) from exc
    stored = [e.model_dump() for e in entries]
    if len({tuple(sorted(e.items())) for e in stored}) != len(stored):
        raise ValueError("contains the same group twice")
    return entries


def _allow_list(value: Any) -> list[dict[str, str]]:
    return [e.model_dump() for e in parse_allow_list(value)]


INT, DEC, BOOL, JSON = (
    SettingDataType.INTEGER,
    SettingDataType.DECIMAL,
    SettingDataType.BOOLEAN,
    SettingDataType.JSON,
)
_POSITIVE = _int(1)

_SPECS = [
    *(SettingSpec(k, JSON, v, _allow_list) for k, v in DEFAULT_CLASSIFICATION_ALLOW_LISTS.items()),
    SettingSpec("analytics.taxable_value_mode", BOOL, True, _bool),
    SettingSpec("analytics.top_n_default", INT, 10, _int(1, 100)),
    SettingSpec("analytics.quarter_mode", JSON, "financial", _choice("financial", "calendar")),
    SettingSpec("cashflow.include_journal", BOOL, False, _bool),
    SettingSpec("aging.bucket_boundaries", JSON, [30, 60, 90], _bucket_boundaries),
    SettingSpec("payment.window_days", INT, 365, _POSITIVE),
    SettingSpec("payment.min_settlements", INT, 3, _POSITIVE),
    SettingSpec("stock.measurement_period_days", INT, 90, _POSITIVE),
    SettingSpec("stock.fast_percentile", INT, 75, _int(1, 99)),
    SettingSpec("stock.slow_threshold_days", INT, 90, _POSITIVE),
    SettingSpec("stock.dead_stock_days", INT, 180, _POSITIVE),
    SettingSpec(
        "stock.fast_ranking_basis", JSON, "quantity", _choice("quantity", "value")
    ),  # D-016
    SettingSpec("reconciliation.money_absolute_tolerance", DEC, "1.00", _decimal()),
    SettingSpec("reconciliation.money_percentage_tolerance", DEC, "0.01", _decimal()),
    SettingSpec("reconciliation.quantity_absolute_tolerance", DEC, "0", _decimal()),
    SettingSpec("reconciliation.quantity_percentage_tolerance", DEC, "0.5", _decimal()),
    # D-033 #10: intervals in minutes; key lists every N incremental runs.
    SettingSpec("sync.incremental_interval", INT, 60, _POSITIVE),
    SettingSpec("sync.full_reconciliation_interval", INT, 1440, _POSITIVE),
    SettingSpec("sync.key_list_interval", INT, 1, _POSITIVE),
    SettingSpec("sync.db_commit_batch", INT, 500, _POSITIVE),
    SettingSpec("sync.keylist_max_missing_ratio", DEC, "0.2", _decimal(positive=True, at_most="1")),
    SettingSpec("agent.poll_interval_seconds", INT, 30, _POSITIVE),
    SettingSpec("agent.offline_threshold_minutes", INT, 5, _POSITIVE),
    SettingSpec("agent.command_claim_timeout_minutes", INT, 10, _POSITIVE),
    SettingSpec("agent.tally_uptime_advisory_days", INT, 7, _POSITIVE),
    # D-035 #11: at least 3 progress intervals (60 s) must fit in one lease.
    SettingSpec("agent.command_lease_seconds", INT, 300, _int(180)),
    SettingSpec("anomaly.history_window_days", INT, 180, _POSITIVE),
    SettingSpec("anomaly.deviation_sd", DEC, "3", _decimal(positive=True)),
    SettingSpec("anomaly.max_multiplier", DEC, None, _decimal(positive=True, nullable=True)),
    SettingSpec("anomaly.duplicate_window_days", INT, 3, _POSITIVE),
]
SETTINGS: dict[str, SettingSpec] = {s.key: s for s in _SPECS}
ALLOW_LIST_KEYS = frozenset(DEFAULT_CLASSIFICATION_ALLOW_LISTS)

# SRS 18.1: boolean only.
FEATURE_FLAGS: dict[str, bool] = {"FEATURE_ANOMALY_DETECTION": False}


def cross_key_errors(effective: Mapping[str, Any]) -> dict[str, str]:
    """Rules between keys, checked on the merged effective values."""
    errors: dict[str, str] = {}
    if effective["stock.dead_stock_days"] <= effective["stock.slow_threshold_days"]:
        errors["stock.dead_stock_days"] = "must be greater than stock.slow_threshold_days"
    return errors


def typed(key: str, stored: Any) -> Any:
    """Stored JSON form -> Python value (DECIMAL settings become Decimal)."""
    if SETTINGS[key].data_type is SettingDataType.DECIMAL and stored is not None:
        return Decimal(stored)
    return stored
