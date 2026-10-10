"""P16.5: a hung test fails in a minute; it does not stall CI for twenty.

`make check` stalled for twenty minutes, twice, because a test blocked waiting on a subprocess
while the process it ran in had been monkey-patched by gevent. Nothing in the suite had a time
limit, so a hang looked exactly like a slow run. pytest-timeout is the guard, and these tests pin
that it is configured the way the failure demands.
"""

import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PYTEST_INI = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"][
    "ini_options"
]


@pytest.mark.req("TEST-1.4")
def test_the_default_limit_is_a_minute_and_uses_the_thread_method() -> None:
    """The slowest test is under fifteen seconds, so 60 s means "hung". `thread`, not `signal`:
    the hang was a test blocked on a subprocess wait, and SIGALRM interrupts only the main
    thread."""
    assert PYTEST_INI["timeout"] == 60
    assert PYTEST_INI["timeout_method"] == "thread"


def test_a_test_blocked_on_a_subprocess_is_killed_not_waited_for(tmp_path: Path) -> None:
    """The failure the guard exists for, reproduced: a test that waits on a child process that
    does not finish. With the limit it ends in a couple of seconds with a message naming the
    timeout; without it, it would run for the full thirty."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntimeout = 2\ntimeout_method = thread\n", encoding="utf-8"
    )
    (tmp_path / "test_hang.py").write_text(
        "import subprocess, sys\n\n\n"
        "def test_waits_on_a_child_that_never_finishes():\n"
        "    subprocess.run([sys.executable, '-c', 'import time; time.sleep(30)'])\n",
        encoding="utf-8",
    )
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=25,
    )
    elapsed = time.monotonic() - started
    assert result.returncode != 0, "the hung test must fail the run"
    assert "Timeout" in result.stdout + result.stderr
    assert elapsed < 20, f"took {elapsed:.0f}s: the limit did not fire"


def test_e2e_tests_get_twice_the_default_and_bench_sync_none() -> None:
    """They start a real uvicorn and a real Agent, and CI runs about twice as slow as a laptop.
    The 100,000-voucher benchmark is four minutes by design and opts out of the limit."""
    conftest = (ROOT / "backend/tests/conftest.py").read_text(encoding="utf-8")
    assert "E2E_TIMEOUT_SECONDS = 120" in conftest
    assert 'item.get_closest_marker("timeout") is None' in conftest
    bench = (ROOT / "backend/tests/e2e/bench_sync.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.timeout(0)" in bench
