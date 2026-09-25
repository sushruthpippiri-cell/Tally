"""P2.8: the settings registry (SRS 18.2 keys, defaults and validators)."""

from decimal import Decimal
from typing import Any

import pytest

from app.core.settings_registry import FEATURE_FLAGS, SETTINGS, cross_key_errors, typed

# SRS 18.2, key for key (paired rows split), with the SRS default where it is a value.
SRS_18_2 = {
    "classification.sales_groups": [{"type": "PREDEFINED", "reserved_name": "Sales Accounts"}],
    "classification.purchase_groups": [
        {"type": "PREDEFINED", "reserved_name": "Purchase Accounts"}
    ],
    "classification.expense_groups": [
        {"type": "PREDEFINED", "reserved_name": "Direct Expenses"},
        {"type": "PREDEFINED", "reserved_name": "Indirect Expenses"},
    ],
    "classification.cash_bank_groups": [
        {"type": "PREDEFINED", "reserved_name": "Cash-in-Hand"},
        {"type": "PREDEFINED", "reserved_name": "Bank Accounts"},
    ],
    "classification.tax_groups": [{"type": "PREDEFINED", "reserved_name": "Duties & Taxes"}],
    "analytics.taxable_value_mode": True,
    "analytics.top_n_default": 10,
    "analytics.quarter_mode": "financial",
    "cashflow.include_journal": False,
    "aging.bucket_boundaries": [30, 60, 90],
    "payment.window_days": 365,
    "payment.min_settlements": 3,
    "stock.measurement_period_days": 90,
    "stock.fast_percentile": 75,
    "stock.slow_threshold_days": 90,
    "stock.dead_stock_days": 180,
    "reconciliation.money_absolute_tolerance": "1.00",
    "reconciliation.money_percentage_tolerance": "0.01",
    "reconciliation.quantity_absolute_tolerance": "0",
    "reconciliation.quantity_percentage_tolerance": "0.5",
    "sync.incremental_interval": 60,  # "Hourly" (D-033 #10)
    "sync.full_reconciliation_interval": 1440,  # "Daily"
    "sync.key_list_interval": 1,  # "Every incremental run"
    "sync.db_commit_batch": 500,
    "agent.poll_interval_seconds": 30,
    "agent.offline_threshold_minutes": 5,
    "agent.command_claim_timeout_minutes": 10,
    "agent.tally_uptime_advisory_days": 7,
    "anomaly.history_window_days": 180,
    "anomaly.deviation_sd": "3",
    "anomaly.max_multiplier": None,  # "Not set (rule inactive)"
    "anomaly.duplicate_window_days": 3,
}
ADDITIONS = {  # D-016, phase-02 P2.8
    "stock.fast_ranking_basis": "quantity",
    "sync.keylist_max_missing_ratio": "0.2",
    "agent.command_lease_seconds": 300,
}


def test_every_srs_18_2_key_with_its_default() -> None:
    assert {k: s.default for k, s in SETTINGS.items()} == SRS_18_2 | ADDITIONS


def test_feature_flags_are_boolean_and_anomaly_is_off() -> None:
    assert FEATURE_FLAGS == {"FEATURE_ANOMALY_DETECTION": False}


def test_every_default_passes_its_own_validator() -> None:
    for key, spec in SETTINGS.items():
        assert spec.validate(spec.default) == spec.default, key


VALID: list[tuple[str, Any, Any]] = [
    ("analytics.top_n_default", 1, 1),
    ("analytics.top_n_default", 100, 100),
    ("reconciliation.money_absolute_tolerance", "0", "0"),
    ("reconciliation.money_percentage_tolerance", "0.05", "0.05"),
    ("reconciliation.quantity_absolute_tolerance", 2, "2"),
    ("aging.bucket_boundaries", [15, 45], [15, 45]),
    ("stock.fast_percentile", 1, 1),
    ("stock.fast_percentile", 99, 99),
    ("sync.keylist_max_missing_ratio", "1", "1"),
    ("anomaly.max_multiplier", "5", "5"),
    ("anomaly.max_multiplier", None, None),
    ("analytics.quarter_mode", "calendar", "calendar"),
    ("stock.fast_ranking_basis", "value", "value"),
    ("cashflow.include_journal", True, True),
    (
        "classification.sales_groups",
        [{"type": "COMPANY_GROUP", "tally_guid": "g-1"}],
        [{"type": "COMPANY_GROUP", "tally_guid": "g-1"}],
    ),
]

INVALID: list[tuple[str, Any]] = [
    ("analytics.top_n_default", 0),
    ("analytics.top_n_default", 101),
    ("analytics.top_n_default", "10"),
    ("analytics.top_n_default", True),
    ("analytics.top_n_default", 10.0),
    ("reconciliation.money_absolute_tolerance", "-0.01"),  # tolerances >= 0
    ("reconciliation.money_percentage_tolerance", 0.01),  # float: send decimals as strings
    ("reconciliation.quantity_percentage_tolerance", "abc"),
    ("reconciliation.quantity_percentage_tolerance", "NaN"),
    ("aging.bucket_boundaries", []),
    ("aging.bucket_boundaries", [30, 30, 90]),  # strictly ascending
    ("aging.bucket_boundaries", [60, 30]),
    ("aging.bucket_boundaries", [0, 30]),  # positive
    ("aging.bucket_boundaries", [30, 45.5]),
    ("aging.bucket_boundaries", "30,60"),
    ("stock.fast_percentile", 0),  # 1-99
    ("stock.fast_percentile", 100),
    ("payment.window_days", 0),  # windows > 0
    ("payment.min_settlements", -1),
    ("stock.measurement_period_days", 0),
    ("anomaly.history_window_days", 0),
    ("anomaly.deviation_sd", "0"),  # thresholds > 0
    ("anomaly.max_multiplier", "0"),
    ("sync.keylist_max_missing_ratio", "0"),
    ("sync.keylist_max_missing_ratio", "1.5"),
    ("sync.db_commit_batch", 0),
    ("agent.poll_interval_seconds", 0),
    ("agent.command_lease_seconds", 179),  # D-035 #11: >= 3 progress intervals
    ("analytics.quarter_mode", "fiscal"),
    ("stock.fast_ranking_basis", "margin"),
    ("cashflow.include_journal", "false"),
    ("analytics.taxable_value_mode", 1),
    ("classification.sales_groups", []),  # non-empty
    ("classification.sales_groups", ["Sales Accounts"]),  # a display name, not a tagged entry
    ("classification.sales_groups", [{"type": "PREDEFINED", "reserved_name": "Sales"}]),
    ("classification.sales_groups", [{"type": "PREDEFINED", "name": "Sales Accounts"}]),
    ("classification.sales_groups", [{"type": "GROUP", "tally_guid": "g-1"}]),
    ("classification.sales_groups", [{"type": "COMPANY_GROUP", "tally_guid": ""}]),
    (
        "classification.sales_groups",
        [{"type": "PREDEFINED", "reserved_name": "Sales Accounts"}] * 2,
    ),
]


@pytest.mark.parametrize(("key", "raw", "stored"), VALID)
def test_valid_values(key: str, raw: Any, stored: Any) -> None:
    assert SETTINGS[key].validate(raw) == stored


@pytest.mark.parametrize(("key", "raw"), INVALID)
def test_invalid_values(key: str, raw: Any) -> None:
    with pytest.raises(ValueError):
        SETTINGS[key].validate(raw)


def test_dead_stock_must_come_after_slow() -> None:
    defaults = {k: s.default for k, s in SETTINGS.items()}
    assert cross_key_errors(defaults) == {}
    assert "stock.dead_stock_days" in cross_key_errors(defaults | {"stock.dead_stock_days": 90})


def test_decimal_settings_are_read_as_decimal() -> None:
    assert typed("reconciliation.money_absolute_tolerance", "1.00") == Decimal("1.00")
    assert typed("anomaly.max_multiplier", None) is None
    assert typed("analytics.top_n_default", 10) == 10
