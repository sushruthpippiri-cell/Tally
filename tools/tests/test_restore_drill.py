"""P16.6: the restore drill's comparison, and the guards on the scripts (BKP-1.2).

The drill itself needs a backup and a staging database, so it is blocked. What can be tested
here is the part that decides whether a restore passed - and the refusal that stops the drill
restoring over production, which is the one mistake in this script that would be unrecoverable.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
BACKUP = ROOT / "deploy/backup"

_spec = importlib.util.spec_from_file_location("compare_snapshot", BACKUP / "compare_snapshot.py")
assert _spec and _spec.loader
compare_snapshot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_snapshot)


def _snapshot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": 1,
        "row_counts": {"vouchers": 1000, "voucher_entries": 5000, "companies": 2},
        "reconciliation": [
            {
                "company_id": "c1",
                "sync_run_id": "r1",
                "overall": "PASS",
                "metric": "total_sales",
                "entity_id": "",
                "local": "2701875.00",
                "tally": "2701875.00",
                "result": "PASS",
            }
        ],
    }
    return base | overrides


def test_an_identical_restore_has_no_differences() -> None:
    assert compare_snapshot.differences(_snapshot(), _snapshot()) == []


@pytest.mark.req("BKP-1.2")
def test_a_missing_row_is_reported_with_both_counts() -> None:
    short = _snapshot(row_counts={"vouchers": 999, "voucher_entries": 5000, "companies": 2})
    problems = compare_snapshot.differences(_snapshot(), short)
    assert problems == ["vouchers: snapshot 1000, restored 999"]


def test_a_missing_table_is_reported_not_skipped() -> None:
    """A restore that brought back no voucher_entries at all would otherwise compare equal to
    nothing and pass."""
    problems = compare_snapshot.differences(_snapshot(), _snapshot(row_counts={"vouchers": 1000}))
    assert any("voucher_entries" in p for p in problems)


@pytest.mark.req("BKP-1.2")
def test_a_changed_reconciliation_figure_is_reported() -> None:
    """Row counts alone would pass a restore that brought back the right *number* of wrong rows.
    The reconciliation figures are the numbers a business would notice."""
    wrong = _snapshot()
    wrong["reconciliation"] = [dict(wrong["reconciliation"][0], local="2700000.00")]
    problems = compare_snapshot.differences(_snapshot(), wrong)
    assert len(problems) == 1 and "total_sales" in problems[0]


def _drill(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BACKUP / "restore_drill.sh"), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **env},
    )


@pytest.mark.skipif(sys.platform == "win32", reason="a bash script; the server runs on Linux")
@pytest.mark.req("BKP-1.2")
def test_the_drill_refuses_a_url_that_is_not_staging(tmp_path: Path) -> None:
    """The one mistake in this script that could not be undone. A drill that restores over
    production is worse than no drill at all."""
    snapshot = tmp_path / "s.json"
    snapshot.write_text("{}", encoding="utf-8")
    result = _drill(
        "--snapshot", str(snapshot), "--staging-url", "postgresql://u:p@host:5432/tally"
    )
    assert result.returncode == 1
    assert "does not end in _staging" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="a bash script; the server runs on Linux")
def test_the_drill_accepts_a_staging_url_but_asks_for_the_restore_command(tmp_path: Path) -> None:
    """It does not guess how a provider restores a backup: managed instances restore through
    their own API, self-hosted ones with pg_restore or pgBackRest (D-056 #2, provider-neutral)."""
    snapshot = tmp_path / "s.json"
    snapshot.write_text("{}", encoding="utf-8")
    result = _drill(
        "--snapshot", str(snapshot), "--staging-url", "postgresql://u:p@host:5432/tally_staging"
    )
    assert result.returncode == 2
    assert "RESTORE_COMMAND is not set" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="a bash script; the server runs on Linux")
def test_the_drill_needs_a_snapshot(tmp_path: Path) -> None:
    result = _drill("--staging-url", "postgresql://u:p@host:5432/tally_staging")
    assert result.returncode == 2 and "--snapshot is required" in result.stderr
