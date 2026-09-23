import logging

import pytest
import structlog

from tally_contract.log import configure_logging, get_logger


def test_get_logger_reaches_caplog(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    get_logger("t").warning("STALE_ALTERID", guid="g1", incoming=106, stored=108)
    (rec,) = [r for r in caplog.records if isinstance(r.msg, dict)]
    assert rec.levelname == "WARNING"
    assert rec.msg["event"] == "STALE_ALTERID"
    assert rec.msg["guid"] == "g1"


def test_bound_context_is_attached(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    structlog.contextvars.bind_contextvars(company_id="c1")
    try:
        get_logger("t").info("hello")
    finally:
        structlog.contextvars.clear_contextvars()
    assert caplog.records[-1].msg["company_id"] == "c1"


def test_prod_renders_json(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved, saved_level = root.handlers[:], root.level
    try:
        configure_logging("prod")
        get_logger("t").info("EVT", n=1)
        err = capsys.readouterr().err
        assert '"event": "EVT"' in err and '"n": 1' in err
    finally:
        root.handlers[:] = saved
        root.setLevel(saved_level)
        configure_logging("test")
