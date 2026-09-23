from pathlib import Path

import pytest

from tally_tools.phase_report import (
    UnsafeDatabase,
    assert_test_database,
    coverage_percent,
    parse_junit,
    render,
)

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="4" failures="1" errors="0" skipped="1">
  <testcase classname="backend.tests.test_a" name="test_ok">
    <properties>
      <property name="req" value="AC-06"/>
      <property name="req" value="SYNC-3.2"/>
    </properties>
  </testcase>
  <testcase classname="backend.tests.test_a" name="test_bad"><failure message="boom"/></testcase>
  <testcase classname="backend.tests.test_a" name="test_skipped">
    <skipped message="waiting on GATE-G23"/></testcase>
  <testcase classname="backend.tests.test_a" name="test_part">
    <properties>
      <property name="req_partial" value="AC-12"/>
      <property name="req_partial" value="SYNC-3.2"/>
    </properties>
  </testcase>
</testsuite></testsuites>
"""
NO_REASON = JUNIT.replace('message="waiting on GATE-G23"', 'message=""')


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5432/tally",
        "postgresql+psycopg://u:p@localhost:5432/tally_dev",
        "postgresql+psycopg://u:p@localhost:5432/production",
        "postgresql+psycopg://u:p@localhost:5432/test",
    ],
)
def test_reset_refuses_anything_not_ending_in_test(url: str) -> None:
    with pytest.raises(UnsafeDatabase, match="_test"):
        assert_test_database(url)


def test_reset_accepts_a_test_database() -> None:
    assert assert_test_database("postgresql+psycopg://u:p@h:5432/tally_test") == "tally_test"


def test_parse_junit_counts_and_collects(tmp_path: Path) -> None:
    path = tmp_path / "r.xml"
    path.write_text(JUNIT, encoding="utf-8")
    suite = parse_junit(path)
    assert (suite.tests, suite.failures, suite.skipped, suite.passed) == (4, 1, 1, 2)
    assert suite.ok is False
    assert suite.req_ids == {"AC-06", "SYNC-3.2"}
    assert suite.partial_ids == {"AC-12", "SYNC-3.2"}
    assert suite.skip_reasons == [("backend.tests.test_a::test_skipped", "waiting on GATE-G23")]


def test_render_marks_fail_and_lists_everything(tmp_path: Path) -> None:
    path = tmp_path / "r.xml"
    path.write_text(JUNIT, encoding="utf-8")
    out = render("05", parse_junit(path), check_ok=True, coverage="88.0%", log_name="p05-x.log")
    assert "**Result: FAIL**" in out
    assert "| Tests run | 4 |" in out and "| Passed | 2 |" in out and "| Failed | 1 |" in out
    assert "waiting on GATE-G23" in out and "AC-06" in out and "SYNC-3.2" in out
    assert "88.0%" in out and "p05-x.log" in out


def test_render_passes_only_when_suite_and_check_are_green(tmp_path: Path) -> None:
    path = tmp_path / "r.xml"
    path.write_text(
        JUNIT.replace('failures="1"', 'failures="0"').replace('<failure message="boom"/>', ""),
        encoding="utf-8",
    )
    suite = parse_junit(path)
    assert "**Result: PASS**" in render("05", suite, True, "90%", "l.log")
    assert "**Result: FAIL**" in render("05", suite, False, "90%", "l.log")


def test_skip_without_reason_forces_fail(tmp_path: Path) -> None:
    path = tmp_path / "r.xml"
    path.write_text(
        NO_REASON.replace('failures="1"', 'failures="0"').replace('<failure message="boom"/>', ""),
        encoding="utf-8",
    )
    suite = parse_junit(path)
    assert suite.skip_reasons[0][1] == "NO REASON GIVEN"
    assert "**Result: FAIL**" in render("05", suite, True, "90%", "l.log")


def test_coverage_percent(tmp_path: Path) -> None:
    assert coverage_percent(tmp_path / "missing.xml") == "not measured"
    cov = tmp_path / "coverage.xml"
    cov.write_text(
        '<?xml version="1.0"?><coverage line-rate="0.8342"></coverage>', encoding="utf-8"
    )
    assert coverage_percent(cov) == "83.4%"


def test_render_never_counts_partial_coverage_as_covered(tmp_path: Path) -> None:
    path = tmp_path / "r.xml"
    path.write_text(JUNIT, encoding="utf-8")
    out = render("05", parse_junit(path), check_ok=True, coverage="88.0%", log_name="l.log")
    covered, partial = out.split("## Partially covered")
    assert "AC-12" not in covered
    # SYNC-3.2 has a full test too, so it is covered and not repeated as partial.
    assert "AC-12" in partial and "SYNC-3.2" not in partial
