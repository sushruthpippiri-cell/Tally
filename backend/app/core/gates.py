"""Gate status plumbing (SRS 7, VAL-1.x). Reads backend/app/config/gate_status.yaml."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from app.core.config import get_settings

GATE_STATUS_PATH = Path(__file__).parents[1] / "config" / "gate_status.yaml"
GateStatus = Literal["NOT_TESTED", "PASSED", "FAILED"]
SyncMode = Literal["INCREMENTAL", "FULL_ONLY"]

# Which gates each collection's incremental sync depends on (phase-00 P0.10).
COLLECTION_GATES: dict[str, tuple[str, ...]] = {
    "LEDGER": ("G1", "G5", "G6", "G7", "G10"),
    "STOCK_ITEM": ("G2", "G5", "G6", "G7", "G10"),
    "VOUCHER": ("G3", "G5", "G6", "G7", "G8"),
    "COST_CENTRE": ("G4", "G5", "G6", "G7", "G10"),
    "GROUP": ("G5", "G6", "G7", "G10"),
    "VOUCHER_TYPE": ("G5", "G6", "G7", "G10"),
    "COMPANY": ("G5", "G6", "G7", "G10"),
}


def load_gate_status(path: Path = GATE_STATUS_PATH) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


@lru_cache
def _default_statuses() -> dict[str, str]:
    return load_gate_status()


def gate_status(gate_id: str, statuses: Mapping[str, str] | None = None) -> str:
    return (statuses if statuses is not None else _default_statuses())[gate_id]


def gate_passed(gate_id: str, statuses: Mapping[str, str] | None = None) -> bool:
    return gate_status(gate_id, statuses) == "PASSED"


def collection_sync_mode(
    collection_type: str,
    statuses: Mapping[str, str] | None = None,
    *,
    allow_unverified: bool | None = None,
) -> SyncMode:
    """FAILED gate → FULL_ONLY (VAL-1.2); all PASSED → INCREMENTAL; otherwise INCREMENTAL only
    when ALLOW_UNVERIFIED_INCREMENTAL (D-029)."""
    found = [gate_status(g, statuses) for g in COLLECTION_GATES[collection_type]]
    if "FAILED" in found:
        return "FULL_ONLY"
    if all(s == "PASSED" for s in found):
        return "INCREMENTAL"
    if allow_unverified is None:
        allow_unverified = bool(get_settings().allow_unverified_incremental)
    return "INCREMENTAL" if allow_unverified else "FULL_ONLY"
