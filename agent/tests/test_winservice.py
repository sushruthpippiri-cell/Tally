"""P7.9: the Windows service wrapper (D-043 #3). Installing and running it as
NT SERVICE\\TallyAgent is on the owner's real-machine checklist
(docs/agent-windows-checklist.md)."""

import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="a Windows service")


def test_stopping_the_service_asks_the_agent_loop_to_finish() -> None:
    import win32service

    from tally_agent import winservice

    service = winservice.TallyAgentService.__new__(winservice.TallyAgentService)
    reported: list[int] = []
    service.ReportServiceStatus = reported.append  # type: ignore[method-assign]

    class Loop:
        stop = threading.Event()

    service.agent = Loop()  # type: ignore[assignment]
    service.SvcStop()
    assert Loop.stop.is_set()
    assert reported == [win32service.SERVICE_STOP_PENDING]
    assert winservice.TallyAgentService._svc_name_ == "TallyAgent"
