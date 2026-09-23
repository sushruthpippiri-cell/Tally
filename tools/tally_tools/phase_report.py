"""End-of-phase verification and report (P0.12, CLAUDE.md "Testing and logs").

Resets the TEST database, migrates it, runs the FULL suite and `make check`, then writes
docs/test-reports/phase-NN.md. Exits non-zero if anything failed, so a phase cannot be
reported done on a red suite.

    uv run python -m tally_tools.phase_report --phase 00
"""

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from tally_tools.run_tests import main as run_tests

ROOT = Path(__file__).parents[2]
GRANTS_SQL = ROOT / "deploy/postgres/grants.sql"
REPORT_DIR = ROOT / "docs/test-reports"
DEFAULT_TEST_DB = "postgresql+psycopg://tally_owner:tally_owner_dev@localhost:5432/tally_test"


class UnsafeDatabase(RuntimeError):
    """Raised when the reset target is not clearly a test database."""


def assert_test_database(url: str) -> str:
    """The reset only ever touches a database whose name ends in `_test`.

    This is what stops the dev database being dropped; `DATABASE_URL` is never read here.
    """
    name = make_url(url).database
    if not name or not name.endswith("_test"):
        raise UnsafeDatabase(
            f"refusing to reset database {name!r}: the name must end in '_test'. "
            "phase_report never resets the dev database."
        )
    return name


def reset_database(url: str) -> str:
    name = assert_test_database(url)
    admin = make_url(url).set(database="postgres").render_as_string(hide_password=False)
    admin_dsn = admin.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    # A fresh database does not inherit the tally_app grants, so re-apply them (SEC-1.15).
    dsn = make_url(url).render_as_string(hide_password=False)
    with psycopg.connect(
        dsn.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as conn:
        conn.execute(GRANTS_SQL.read_text(encoding="utf-8"))
    return name


@dataclass
class Suite:
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    skip_reasons: list[tuple[str, str]] = field(default_factory=list)
    req_ids: set[str] = field(default_factory=set)
    partial_ids: set[str] = field(default_factory=set)

    @property
    def passed(self) -> int:
        return self.tests - self.failures - self.errors - self.skipped

    @property
    def ok(self) -> bool:
        return self.failures == 0 and self.errors == 0


def parse_junit(path: Path) -> Suite:
    root = ET.parse(path).getroot()
    suites = root.iter("testsuite") if root.tag == "testsuites" else [root]
    result = Suite()
    for node in suites:
        result.tests += int(node.get("tests", 0))
        result.failures += int(node.get("failures", 0))
        result.errors += int(node.get("errors", 0))
        result.skipped += int(node.get("skipped", 0))
        for case in node.iter("testcase"):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            for skipped in case.iter("skipped"):
                reason = (skipped.get("message") or "").strip()
                result.skip_reasons.append((name, reason or "NO REASON GIVEN"))
            for prop in case.iter("property"):
                value = prop.get("value")
                if value and prop.get("name") == "req":
                    result.req_ids.add(value)
                elif value and prop.get("name") == "req_partial":
                    result.partial_ids.add(value)
    return result


def coverage_percent(path: Path) -> str:
    if not path.is_file():
        return "not measured"
    rate = ET.parse(path).getroot().get("line-rate")
    return f"{float(rate) * 100:.1f}%" if rate else "not measured"


def render(phase: str, suite: Suite, check_ok: bool, coverage: str, log_name: str) -> str:
    acs = sorted(i for i in suite.req_ids if i.startswith("AC-"))
    reqs = sorted(i for i in suite.req_ids if not i.startswith("AC-"))
    partial = sorted(suite.partial_ids - suite.req_ids)  # never counted as covered
    missing_reason = [n for n, r in suite.skip_reasons if r == "NO REASON GIVEN"]
    green = suite.ok and check_ok and not missing_reason
    lines = [
        f"# Phase {phase} test report",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `make phase-report "
        f"PHASE={phase}`, on a freshly created and migrated `_test` database.",
        "",
        f"**Result: {'PASS' if green else 'FAIL'}**",
        "",
        "| | |",
        "|---|---|",
        f"| Tests run | {suite.tests} |",
        f"| Passed | {suite.passed} |",
        f"| Failed | {suite.failures + suite.errors} |",
        f"| Skipped | {suite.skipped} |",
        f"| Coverage (lines) | {coverage} |",
        f"| `make check` (lint, types, imports) | {'PASS' if check_ok else 'FAIL'} |",
        f"| Log | `logs/test-runs/{log_name}` |",
        "",
        "## Skipped tests",
        "",
    ]
    if suite.skip_reasons:
        lines += ["| Test | Reason |", "|---|---|"]
        lines += [f"| {n} | {r} |" for n, r in sorted(suite.skip_reasons)]
    else:
        lines.append("_none_")
    lines += [
        "",
        "## Acceptance criteria covered",
        "",
        (", ".join(acs) if acs else "_none_"),
        "",
        "## Other requirement IDs covered",
        "",
        (", ".join(reqs) if reqs else "_none_"),
        "",
        "## Partially covered (not counted as covered)",
        "",
        (", ".join(partial) if partial else "_none_"),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, help="phase number, e.g. 00")
    parser.add_argument("--database-url", default=DEFAULT_TEST_DB)
    args = parser.parse_args(argv)
    phase = args.phase.removeprefix("P").removeprefix("p")

    name = reset_database(args.database_url)
    sys.stdout.write(f"reset database {name}\n")
    migrate = subprocess.run(["make", "migrate"], cwd=ROOT)

    runs = ROOT / "logs/test-runs"
    before = set(runs.glob("*.xml")) if runs.is_dir() else set()
    tests_code = run_tests(["--phase", f"p{phase}", "--cov"])
    new_xml = sorted(set(runs.glob("*.xml")) - before)
    if not new_xml:
        sys.stderr.write("no JUnit XML produced\n")
        return 1
    xml_path = new_xml[-1]

    check = subprocess.run(["make", "lint", "typecheck", "importlint"], cwd=ROOT)
    suite = parse_junit(xml_path)
    check_ok = check.returncode == 0 and migrate.returncode == 0
    report = render(
        phase, suite, check_ok, coverage_percent(ROOT / "coverage.xml"), xml_path.stem + ".log"
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPORT_DIR / f"phase-{phase}.md"
    dest.write_text(report, encoding="utf-8")
    sys.stdout.write(f"\nwrote {dest.relative_to(ROOT)}\n")

    missing_reason = [n for n, r in suite.skip_reasons if r == "NO REASON GIVEN"]
    if missing_reason:
        sys.stderr.write(f"skips without a reason: {', '.join(missing_reason)}\n")
    ok = suite.ok and check_ok and tests_code == 0 and not missing_reason
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
