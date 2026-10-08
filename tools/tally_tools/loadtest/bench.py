"""PERF-1.1 on the benchmark dataset (P16.5).

`make loadtest` points Locust at whatever backend is already running - in practice the dev one,
on `make demo-data`'s four months of trading, where dataset size is most of what the figure
measures. This runs the same Locust file against a backend serving **`tally_bench`**: 100,000
vouchers, 500,000 entries, 5,000 ledgers, 10,000 stock items (SRS 17.2).

    make bench-data        # once, if tally_bench is empty or stale
    make loadtest-bench

It seeds an owner (idempotent), starts uvicorn on a free port against `tally_bench`, runs Locust
against it and stops the server. Still **not** PERF-VAL-1 evidence - a developer machine, no
Windows, no measured link - so the figure is our own share of the budget and the report says so.
"""

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

ROOT = Path(__file__).parents[3]
BENCH_APP_URL = "postgresql+asyncpg://tally_app:tally_app_dev@localhost:5432/tally_bench"
EMAIL = "loadtest@example.com"
PASSWORD = "loadtest-password-16"  # noqa: S105 - a local benchmark database, never deployed


async def seed_owner(url: str, email: str = EMAIL, password: str = PASSWORD) -> str:
    """An Owner on the benchmark company, so Locust can sign in. Idempotent."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.cli import create_owner
    from app.core.security import hash_password
    from app.models.company import Company, Role, User, UserRole
    from app.models.enums import RoleName

    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            company = (await session.execute(select(Company.company_id))).scalars().first()
            if company is None:
                raise SystemExit("tally_bench is empty: run `make bench-data` first")
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                try:
                    await create_owner(session, email, "Load Test", password)
                except Exception:  # the audit row needs a company; fall back to a plain insert
                    user = User(
                        email=email, name="Load Test", password_hash=hash_password(password)
                    )
                    session.add(user)
                    await session.flush()
                user = (await session.execute(select(User).where(User.email == email))).scalar_one()
            role = (
                await session.execute(select(Role).where(Role.role_name == RoleName.OWNER.value))
            ).scalar_one()
            existing = await session.get(UserRole, (user.user_id, company, role.role_id))
            if existing is None:
                session.add(
                    UserRole(user_id=user.user_id, company_id=company, role_id=role.role_id)
                )
        return str(company)
    finally:
        await engine.dispose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def _serving(url: str, env: dict[str, str], port: int) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],  # fmt: skip
        cwd=ROOT / "backend",
        env=env,
    )
    for _ in range(300):
        try:
            if httpx.get(f"{url}/health", timeout=1, trust_env=False).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            raise SystemExit(f"the backend exited with {proc.returncode}")
        time.sleep(0.1)
    proc.terminate()
    raise SystemExit("the backend did not start")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.loadtest.bench")
    parser.add_argument("--url", default=BENCH_APP_URL)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--run-time", default="2m")
    args = parser.parse_args(argv)

    company = asyncio.run(seed_owner(args.url))
    sys.stdout.write(f"benchmark company {company}\n")

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    env = os.environ | {
        "PYTHONPATH": str(ROOT / "backend"),
        "ENV": "dev",
        "DATABASE_URL": args.url,
        "DATABASE_MIGRATION_URL": args.url.replace("+asyncpg", "+psycopg"),
        "SCHEDULER_ENABLED": "false",  # a benchmark measures requests, not background jobs
        "JWT_SECRET": "loadtest-only-secret-not-for-any-deployment-32b",
    }
    backend = _serving(url, env, port)
    try:
        locust = subprocess.run(
            [
                "uv",
                "run",
                "--group",
                "dev",
                "locust",
                "-f",
                str(ROOT / "tools/tally_tools/loadtest/locustfile.py"),
                "--headless",
                "--users",
                str(args.users),
                "--spawn-rate",
                str(args.users),
                "--run-time",
                args.run_time,
                "--host",
                url,
                "--csv",
                str(ROOT / "logs/loadtest-bench"),
            ],  # fmt: skip
            cwd=ROOT,
            env=os.environ
            | {
                "LOAD_EMAIL": EMAIL,
                "LOAD_PASSWORD": PASSWORD,
                "LOAD_FROM": "2025-04-01",
                "LOAD_TO": "2026-03-31",
            },
        )
        return locust.returncode
    finally:
        backend.terminate()
        backend.wait(10)


if __name__ == "__main__":
    raise SystemExit(main())
