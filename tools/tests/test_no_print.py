import subprocess
import sys
from pathlib import Path


def test_print_is_rejected_by_ruff(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_text("print('x')\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "T20", str(f)],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "T201" in r.stdout


def test_repo_ruff_config_selects_t20() -> None:
    import tomllib

    cfg = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    assert "T20" in cfg["tool"]["ruff"]["lint"]["select"]
