import logging
from pathlib import Path

import pytest

from tally_contract.log import get_logger
from tally_contract.testing import assert_logged, assert_not_logged


def test_assert_logged_matches_event_level_and_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    get_logger("t").error("UDF_NOT_FOUND", field="X", run=3)
    found = assert_logged(caplog, "UDF_NOT_FOUND", level="ERROR", field="X")
    assert found["run"] == 3


def test_assert_logged_fails_when_missing_or_mismatched(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    get_logger("t").warning("A", k=1)
    with pytest.raises(AssertionError, match="B"):
        assert_logged(caplog, "B")
    with pytest.raises(AssertionError):
        assert_logged(caplog, "A", k=2)
    with pytest.raises(AssertionError):
        assert_logged(caplog, "A", level="ERROR")


def test_assert_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    get_logger("t").info("A")
    assert_not_logged(caplog, "B")
    with pytest.raises(AssertionError):
        assert_not_logged(caplog, "A")


def test_skip_without_reason_is_a_failure(pytester: pytest.Pytester) -> None:
    pytester.makeconftest((Path(__file__).parents[2] / "conftest.py").read_text())
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makepyfile("import pytest\ndef test_x():\n    pytest.skip()\n")
    pytester.runpytest("-p", "pytester").assert_outcomes(failed=1)
