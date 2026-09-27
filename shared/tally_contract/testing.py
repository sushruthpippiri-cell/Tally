"""Test helpers: assert on structured log records, not only on return values."""

from datetime import UTC, datetime
from typing import Any

import pytest

# The instant every test starts at (root conftest.py): tests never see the real date. Noon UTC,
# so the local date is the same in every time zone from UTC-11 to UTC+11.
FIXED_NOW = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)


def _events(caplog: pytest.LogCaptureFixture) -> list[tuple[str, dict[str, Any]]]:
    return [(r.levelname, r.msg) for r in caplog.records if isinstance(r.msg, dict)]


def _matches(
    levelname: str, msg: dict[str, Any], event: str, level: str | None, fields: dict[str, Any]
) -> bool:
    return (
        msg.get("event") == event
        and (level is None or levelname == level.upper())
        and all(k in msg and msg[k] == v for k, v in fields.items())
    )


def assert_logged(
    caplog: pytest.LogCaptureFixture, event: str, *, level: str | None = None, **fields: Any
) -> dict[str, Any]:
    """Return the first record with this event (and level / field values), else fail."""
    events = _events(caplog)
    for levelname, msg in events:
        if _matches(levelname, msg, event, level, fields):
            return msg
    seen = [f"{lv} {m.get('event')} {m}" for lv, m in events] or ["(no structured records)"]
    raise AssertionError(
        f"log record not found: event={event!r} level={level!r} fields={fields!r}\n"
        "seen:\n  " + "\n  ".join(seen)
    )


def assert_not_logged(
    caplog: pytest.LogCaptureFixture, event: str, *, level: str | None = None, **fields: Any
) -> None:
    for levelname, msg in _events(caplog):
        if _matches(levelname, msg, event, level, fields):
            raise AssertionError(f"unexpected log record: event={event!r} {msg}")
