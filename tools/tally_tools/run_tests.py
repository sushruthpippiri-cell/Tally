"""Run the test suite, saving output and a JUnit XML per run (P0.12).

    uv run python -m tally_tools.run_tests --phase p05 [-- pytest args]

Writes logs/test-runs/<phase>-<UTC timestamp>.log and .xml. `logs/` is git-ignored.
"""

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
LOG_DIR = ROOT / "logs/test-runs"


def run_paths(phase: str, extra: list[str], timestamp: str | None = None) -> tuple[Path, Path]:
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{phase}-{stamp}"
    return LOG_DIR / f"{stem}.log", LOG_DIR / f"{stem}.xml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="dev")
    parser.add_argument("--cov", action="store_true", help="also write coverage.xml")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args(argv)

    log_path, xml_path = run_paths(args.phase, args.pytest_args)
    cmd = ["uv", "run", "pytest", f"--junitxml={xml_path}", *args.pytest_args]
    if args.cov:
        cmd += ["--cov", "--cov-report=xml", "--cov-report=term-missing:skip-covered"]

    with log_path.open("w", encoding="utf-8") as log:
        header = f"$ {' '.join(cmd)}\n"
        sys.stdout.write(header)
        log.write(header)
        proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for line in proc.stdout:  # tee: terminal and file
            sys.stdout.write(line)
            log.write(line)
        code = proc.wait()
        log.write(f"\nexit={code}\n")
    sys.stdout.write(f"\nlog: {log_path.relative_to(ROOT)}\njunit: {xml_path.relative_to(ROOT)}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
