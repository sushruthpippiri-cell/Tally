"""P7.5-P7.7: the Agent runs sync commands against the mock Tally and a fake backend that
enforces the protocol (docs/agent-protocol.md): the owner's session-2 tests (progress timer,
dates from the backend), AC-21, AC-23, AC-24, and the heartbeat."""

import threading
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from tally_agent import AGENT_VERSION
from tally_agent.executor import Executor
from tally_agent.queue import BATCH, Limits
from tally_agent.uploader import Uploader
from tally_contract import tally_constants as tc
from tally_contract.testing import assert_logged
from tally_tools.mock_tally import add_voucher, company_guid

SHARMA = "Sharma Traders"


def voucher_calls(mock: Any) -> list[dict[str, str]]:
    return [c for c in mock.calls if c["report"] == "TA_Vouchers"]


# --- a whole command -----------------------------------------------------------------------


def test_a_full_sync_uploads_every_collection_in_order_and_completes(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    fake_backend.plan["collections"]["GROUP"]["key_list_due"] = True
    agent = make_agent()
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert outcome is not None and outcome.status == "COMPLETED", outcome
    assert fake_backend.results == [{"status": "COMPLETED"}]
    assert [f["status"] for f in fake_backend.finishes] == ["COMPLETED"]
    uploaded = [b["collection_type"] for b in fake_backend.batches]
    assert uploaded == [
        "COMPANY", "GROUP", "VOUCHER_TYPE", "LEDGER", "COST_CENTRE", "STOCK_ITEM", None, "VOUCHER"
    ]  # fmt: skip
    vouchers = [
        r for b in fake_backend.batches if b["collection_type"] == "VOUCHER" for r in b["records"]
    ]
    assert len(vouchers) == 12
    assert [v["alter_id"] for v in vouchers] == sorted(v["alter_id"] for v in vouchers)  # D-026
    [snapshot] = [b for b in fake_backend.batches if b["collection_type"] is None]
    assert snapshot["records"][0]["as_of_date"] == "2026-03-16"  # the plan's as_of
    [keys] = fake_backend.key_lists
    assert (keys["collection_type"], keys["is_final"], len(keys["keys"])) == ("GROUP", True, 3)
    released = [r["collection_type"] for r in fake_backend.releases]
    assert released == [
        "COMPANY",
        "GROUP",
        "VOUCHER_TYPE",
        "LEDGER",
        "COST_CENTRE",
        "STOCK_ITEM",
        "VOUCHER",
    ]
    assert agent.queue.status().records == 0


@pytest.mark.req("SEC-2.0a")
def test_every_call_carries_the_agents_credential_as_a_bearer_token(
    make_agent: Any, run_agent_once: Any, fake_backend: Any
) -> None:
    agent = make_agent()
    fake_backend.offer("FULL")
    run_agent_once(agent)
    headers = [h for _, _, _, h in fake_backend.calls]
    assert len(headers) > 20
    assert {h.get("Authorization") for h in headers} == {f"Bearer {fake_backend.credential}"}


# --- owner item 1: progress on its own timer ------------------------------------------------


@pytest.mark.req("AGT-1.7")
def test_a_tally_request_longer_than_the_lease_does_not_lose_the_command(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    """Owner (D-042 #1): the mock Tally answers the voucher pull after 3x the command lease,
    while the fake backend expires any command that goes a lease without progress. Progress
    arrives every interval from its own thread, so the command stays RUNNING and completes."""
    mock, _ = mock_tally
    agent = make_agent(command_lease_seconds=3, progress_interval_seconds=1, tally_timeout=60)
    mock.slow["TA_Vouchers"] = [9.0]  # 3 x the lease
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert outcome is not None and outcome.status == "COMPLETED", outcome
    assert fake_backend.results == [{"status": "COMPLETED"}]
    beats = [t for t, path in fake_backend.times if path.endswith("/progress")]
    assert len(beats) >= 9
    assert max(b - a for a, b in zip(beats, beats[1:], strict=False)) < 2.0  # never near the lease


# --- owner item 5: dates come from the backend ----------------------------------------------


def test_dates_come_from_the_plan_never_from_this_pcs_clock(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    """Owner (D-042 #5): this PC's clock says 2031; the backend says today is 2026-03-16 in
    company time and books begin 2025-11-20. The snapshot and every date page use the plan."""
    mock, _ = mock_tally
    fake_backend.plan["collections"]["VOUCHER"]["mode"] = "FULL_ONLY"  # date pages
    fake_backend.plan["full_pull_from"] = "2025-11-20"
    agent = make_agent()
    fake_backend.offer("INCREMENTAL")
    with time_machine.travel(datetime(2031, 6, 1, 9, 0, tzinfo=UTC), tick=True):
        outcome = run_agent_once(agent)
    assert outcome is not None and outcome.status == "COMPLETED", outcome
    pages = voucher_calls(mock)
    assert pages[0][tc.VAR_FROM_DATE] == "20251120"
    assert pages[-2][tc.VAR_TO_DATE] == "20260316"
    # D-048 #2: then one page for everything dated after today (post-dated vouchers)
    assert (pages[-1][tc.VAR_FROM_DATE], pages[-1][tc.VAR_TO_DATE]) == ("20260317", "20991231")
    assert all(p[tc.VAR_FROM_ALTER_ID] == "0" for p in pages)  # a full-only collection: no windows
    [stock] = [c for c in mock.calls if c["report"] == tc.STOCK_CLOSING_REPORT]
    assert stock[tc.VAR_TO_DATE] == "20260316"
    [snapshot] = [b for b in fake_backend.batches if b["collection_type"] is None]
    assert snapshot["records"][0]["as_of_date"] == "2026-03-16"


# --- D-048 #2: every voucher request names its dates -----------------------------------------


@pytest.mark.parametrize("mode", ["INCREMENTAL", "FULL_ONLY"])
def test_every_voucher_request_names_its_dates_whatever_period_tally_has_selected(
    make_agent: Any,
    run_agent_once: Any,
    fake_backend: Any,
    mock_tally: tuple[Any, str],
    mode: str,
) -> None:
    """Owner (D-048 #2, GATE-G37): the Tally user has selected one month; our pulls and key
    lists still get every voucher, post-dated ones included, because every request names
    books-beginning to FULL_PULL_DATE_TO. The voucher key list carries that date window."""
    mock, _ = mock_tally
    fake_backend.plan["collections"]["VOUCHER"] |= {"mode": mode, "key_list_due": True}
    agent = make_agent()
    add_voucher(mock.data, date(2026, 4, 1))  # post-dated: after the plan's today, 2026-03-16
    mock.selected_period = (date(2024, 5, 1), date(2024, 5, 31))
    fake_backend.offer("INCREMENTAL")
    assert run_agent_once(agent).status == "COMPLETED"
    requests = [c for c in mock.calls if c["report"] in ("TA_Vouchers", "TA_VouchersKeys")]
    assert requests and all(c.get(tc.VAR_FROM_DATE) and c.get(tc.VAR_TO_DATE) for c in requests)
    vouchers = {
        r["guid"] for b in fake_backend.batches if b["collection_type"] == "VOUCHER"
        for r in b["records"]
    }  # fmt: skip
    assert vouchers == {f"v-{i}" for i in range(1, 14)}
    [keys] = [k for k in fake_backend.key_lists if k["collection_type"] == "VOUCHER"]
    assert len(keys["keys"]) == 13
    assert keys["window"] == {
        "kind": "DATE",
        "date_from": "2024-04-01",
        "date_to": "2099-12-31",
    }


# --- AC-21: a full queue --------------------------------------------------------------------


@pytest.mark.req("AC-21", "AGT-2.4")
def test_a_full_queue_stops_pulling_keeps_uploading_and_is_reported(
    make_agent: Any,
    fake_backend: Any,
    mock_tally: tuple[Any, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock, _ = mock_tally
    agent = make_agent(limits=Limits(max_records=2))
    fake_backend.running("cmd-1")
    for n in (1, 2):
        agent.queue.add(
            kind=BATCH, item_id=f"b{n}", command_id="cmd-1", sync_run_id="run-1",
            collection="VOUCHER", body_json='{"records": []}', record_count=1,
        )  # fmt: skip
    assert agent.heartbeat_payload()["queue_status"]["full"] is True  # QUEUE_FULL reported
    requests_before = len(mock.calls)
    lost = threading.Event()
    executor = Executor(
        settings=agent.settings, config=agent.config, registered_guid=company_guid(SHARMA),
        backend=agent.backend(), tally=agent.tally, queue=agent.queue, lost=lost,
    )  # fmt: skip
    waiting = threading.Thread(target=executor._wait_for_room, daemon=True)
    waiting.start()
    time.sleep(0.5)
    assert waiting.is_alive() and len(mock.calls) == requests_before  # nothing pulled
    assert_logged(caplog, "queue_full", level="warning", code="QUEUE_FULL")
    stop = threading.Event()
    uploader = threading.Thread(
        target=Uploader(agent.queue, agent.backend, stop, idle_seconds=0.02).run, daemon=True
    )
    uploader.start()  # uploads continue while full...
    waiting.join(5)
    stop.set()
    uploader.join(5)
    assert not waiting.is_alive()  # ...and once there is room, pulling resumes
    assert len(fake_backend.batches) == 2


# --- AC-23 and the company checks -----------------------------------------------------------


@pytest.mark.req("AC-23", "AGT-5.1", "AGT-5.3")
def test_only_the_registered_company_is_pulled_and_a_closed_one_pulls_nothing(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    mock, _ = mock_tally  # "Other Co" is loaded too
    agent = make_agent()
    fake_backend.offer("FULL")
    assert run_agent_once(agent).status == "COMPLETED"
    assert {c.get(tc.VAR_COMPANY) for c in mock.calls} == {SHARMA}
    mock.calls.clear()
    fake_backend.batches.clear()
    mock.companies = ["Other Co"]  # the registered company is closed
    agent.stop.clear()
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert (outcome.status, outcome.error_code) == ("FAILED", "COMPANY_NOT_LOADED")
    assert [c["report"] for c in mock.calls] == [
        tc.INFO_REPORT,
        tc.INFO_REPORT,
    ]  # heartbeat, preflight
    assert fake_backend.batches == []
    assert fake_backend.results[-1]["error_code"] == "COMPANY_NOT_LOADED"


@pytest.mark.req("AGT-5.4")
def test_a_renamed_company_is_reported_and_needs_only_the_new_name_not_a_new_registration(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    mock, _ = mock_tally
    agent = make_agent()
    mock.companies = ["Sharma Traders Pvt Ltd", "Other Co"]  # renamed in Tally; same GUID
    mock.guids["Sharma Traders Pvt Ltd"] = company_guid(SHARMA)
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert (outcome.status, outcome.error_code) == ("FAILED", "COMPANY_NOT_LOADED")
    # An Owner/Admin updates the stored name (Agent Tally settings); the next heartbeat brings it.
    fake_backend.config["tally_company_name"] = "Sharma Traders Pvt Ltd"
    agent.stop.clear()
    fake_backend.offer("FULL")
    assert run_agent_once(agent).status == "COMPLETED"
    assert agent.state.company_guid == company_guid(SHARMA)  # never re-registered


@pytest.mark.req("AGT-3.2", "AGT-3.3")
def test_a_company_mismatch_halts_before_anything_is_pulled_or_uploaded(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    mock, _ = mock_tally
    agent = make_agent()
    mock.guids[SHARMA] = "guid-of-a-restored-backup"
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert (outcome.status, outcome.error_code) == ("FAILED", "COMPANY_MISMATCH")
    assert {c["report"] for c in mock.calls} == {tc.INFO_REPORT}
    assert fake_backend.paths("/agent/leases") == []
    assert not any("/batches" in p or "/runs" in p for p in fake_backend.paths())
    assert fake_backend.results == [
        {"status": "FAILED", "error_code": "COMPANY_MISMATCH", "error_message": outcome.message}
    ]


# --- AC-24: timeouts -----------------------------------------------------------------------


@pytest.mark.req("AGT-4.3")
@pytest.mark.req_partial("AC-24")  # batch sizes over 10,000 refused: test_agent_management.py
def test_a_timed_out_window_is_retried_once_at_half_size(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str],
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    mock, _ = mock_tally
    agent = make_agent(tally_timeout=1.0)
    mock.slow["TA_Vouchers"] = [2.0]
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert outcome.status == "COMPLETED" and fake_backend.finishes[-1]["problems"] == []
    windows = [(c[tc.VAR_FROM_ALTER_ID], c[tc.VAR_TO_ALTER_ID]) for c in voucher_calls(mock)]
    assert windows == [("0", "12"), ("0", "6"), ("6", "12")]
    assert_logged(caplog, "tally_export_timeout", level="warning", code="TALLY_EXPORT_TIMEOUT")
    vouchers = [
        r for b in fake_backend.batches if b["collection_type"] == "VOUCHER" for r in b["records"]
    ]
    assert len(vouchers) == 12


def test_a_second_timeout_fails_the_segment_and_is_reported(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, mock_tally: tuple[Any, str]
) -> None:
    mock, _ = mock_tally
    agent = make_agent(tally_timeout=1.0)
    mock.slow["TA_Vouchers"] = [2.0, 2.0]
    fake_backend.offer("FULL")
    assert run_agent_once(agent).status == "COMPLETED"  # the backend makes the run PARTIAL
    [problem] = fake_backend.finishes[-1]["problems"]
    assert (problem["collection_type"], problem["code"]) == ("VOUCHER", "TALLY_EXPORT_TIMEOUT")
    assert not [b for b in fake_backend.batches if b["collection_type"] == "VOUCHER"]


# --- leases and a lost command --------------------------------------------------------------


def test_a_locked_collection_is_skipped_and_noted(
    make_agent: Any, run_agent_once: Any, fake_backend: Any
) -> None:
    fake_backend.locked = {"LEDGER"}
    agent = make_agent()
    fake_backend.offer("FULL")
    assert run_agent_once(agent).status == "COMPLETED"
    assert not [b for b in fake_backend.batches if b["collection_type"] == "LEDGER"]
    assert [(p["collection_type"], p["code"]) for p in fake_backend.finishes[-1]["problems"]] == [
        ("LEDGER", "SYNC_LOCKED")
    ]


def test_a_command_lost_mid_run_stops_and_leaves_nothing_queued(
    make_agent: Any, run_agent_once: Any, fake_backend: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """D-039, D-042 #6: once the command is lost nothing more is uploaded or reported; the
    next run re-pulls what was not stored."""
    agent = make_agent(command_lease_seconds=3, progress_interval_seconds=1)
    fake_backend.lose_after_batches = 2
    fake_backend.offer("FULL")
    outcome = run_agent_once(agent)
    assert outcome is not None and outcome.status is None
    assert fake_backend.results == [] and fake_backend.finishes == []
    assert agent.queue.status().records == 0
    assert_logged(caplog, "command_abandoned", level="warning")


# --- the heartbeat (P7.7) -------------------------------------------------------------------


@pytest.mark.req("VER-1.1", "AGT-6.3")
@pytest.mark.req_partial("AC-25", "AGT-1.1")  # the advisory itself: backend P3; the poll timer
def test_the_heartbeat_reports_versions_tally_and_the_queue(
    make_agent: Any, fake_processes: Any
) -> None:
    eight_days = time.time() - 8 * 86_400
    agent = make_agent(processes=fake_processes(started_at=eight_days))
    payload = agent.heartbeat_payload()
    assert payload | {"tally_uptime_seconds": 0} == {
        "agent_version": AGENT_VERSION,
        "tdl_version": tc.TDL_VERSION,
        "tally_version": None,
        "tally_uptime_seconds": 0,
        "queue_status": {
            "records": 0,
            "oldest_age_seconds": None,
            "dead_letter_count": 0,
            "full": False,
        },
        "tally_status": "OK",
        "confirmed_tally_guid": company_guid(SHARMA),
    }
    assert payload["tally_uptime_seconds"] >= 8 * 86_400


@pytest.mark.req("FR-1.4")
@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"tdl_loaded": False}, "TDL_NOT_LOADED"),
        ({"companies": ["Other Co"]}, "COMPANY_NOT_LOADED"),
        ({"guids": {SHARMA: "another"}}, "COMPANY_MISMATCH"),
        ({"tdl_version": "9.9.9"}, "TDL_NOT_LOADED"),
    ],
)
def test_the_heartbeat_reports_what_is_wrong_with_tally(
    make_agent: Any, mock_tally: tuple[Any, str], change: dict[str, Any], status: str
) -> None:
    mock, _ = mock_tally
    agent = make_agent()
    for key, value in change.items():
        setattr(mock, key, value)
    assert agent.heartbeat_payload()["tally_status"] == status
    assert all(c["report"] == tc.INFO_REPORT for c in mock.calls)  # never a default report


def test_a_revoked_agent_stops_and_a_rotated_credential_waits(
    make_agent: Any, fake_backend: Any
) -> None:
    agent = make_agent()
    fake_backend.heartbeat_error = (401, {"code": "CREDENTIAL_INVALID", "message": "rotated"})
    agent.tick()
    assert not agent.stop.is_set()
    fake_backend.heartbeat_error = (403, {"code": "AGENT_REVOKED", "message": "revoked"})
    agent.tick()
    assert agent.stop.is_set() and agent.revoked
