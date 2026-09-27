"""D-040 #1: every code that can be written to sync_errors is classified NOT_STORED or INFO.

Finds the codes by reading the source, so a code added in a later phase fails here until it is
classified: `ErrorCode.X` inside any call that builds a failure or a sync_errors row, the Agent's
ParseError default, and the codes `finish` accepts from the Agent.
"""

import ast
from pathlib import Path
from typing import get_args

import pytest

from app.schemas.sync import RunProblem
from app.sync.context import SYNC_ERROR_KIND, error_row
from tally_contract.errors import ErrorCode
from tally_contract.records import ParseError

ROOT = Path(__file__).parents[3]
SOURCES = [ROOT / "backend/app", ROOT / "shared/tally_contract"]
# Calls whose ErrorCode ends up in sync_errors: records the backend could not store, records the
# parser rejected (they reach the backend as ParseError), and rows built directly.
BUILDERS = {"RecordFailure", "RecordRejected", "ParseError", "error_row", "SyncError"}


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def written_codes() -> set[str]:
    found: set[str] = set()
    for base in SOURCES:
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in ast.walk(tree):
                if isinstance(call, ast.Call) and _name(call.func) in BUILDERS:
                    for node in ast.walk(call):
                        if (
                            isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "ErrorCode"
                        ):
                            found.add(node.attr)
    return found


def test_every_code_written_to_sync_errors_is_classified() -> None:
    codes = written_codes()
    codes.add(ParseError.model_fields["code"].default.name)
    codes |= set(get_args(RunProblem.model_fields["code"].annotation))
    # The scan must see the writers it is meant to police.
    assert {"UNKNOWN_MASTER_REFERENCE", "STALE_ALTERID", "CHUNK_FAILED", "AGENT_LOST"} <= codes
    assert codes <= {c.name for c in SYNC_ERROR_KIND}, codes - {c.name for c in SYNC_ERROR_KIND}


def test_an_unclassified_code_cannot_be_written() -> None:
    with pytest.raises(ValueError, match="not classified"):
        error_row(
            company_id=None,  # type: ignore[arg-type]
            sync_run_id=None,  # type: ignore[arg-type]
            entity_type="RUN",
            code=ErrorCode.QUEUE_FULL,
            message="x",
        )
