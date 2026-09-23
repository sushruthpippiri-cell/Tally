"""Text I/O must name its encoding.

Windows defaults to cp1252, so `Path.read_text()` raises UnicodeDecodeError on any file holding
a rupee sign or an em dash - and the Agent ships to Windows machines. Ruff's PLW1514 is a preview
rule and misses pathlib call sites, so this guard scans the source instead.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
# No dot in the lookbehind: `.read_text(` must match; `reopen(`/`Popen(` must not.
CALL = re.compile(r"(?<!\w)(?:open|read_text|write_text)\s*\(", re.M)
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", "logs"}


def _source_files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*.py")
        if not SKIP_DIRS & set(p.relative_to(ROOT).parts) and p.name != "test_text_io_encoding.py"
    ]


def _call_source(text: str, start: int) -> str:
    """The text of one call, from its opening paren to the matching close."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def test_every_text_io_call_names_an_encoding() -> None:
    offenders: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for match in CALL.finditer(text):
            call = _call_source(text, match.end() - 1)
            if "encoding=" in call or '"rb"' in call or '"wb"' in call or "newline=" in call:
                continue
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}: {match.group().strip()}")
    assert not offenders, "text I/O without encoding=\n  " + "\n  ".join(offenders)


def test_guard_detects_a_bad_call(tmp_path: Path) -> None:
    """The guard must actually fail on an unencoded call, not vacuously pass."""
    bad = tmp_path / "bad.py"
    bad.write_text("from pathlib import Path\nPath('x').read_text()\n", encoding="utf-8")
    text = bad.read_text(encoding="utf-8")
    match = CALL.search(text)
    assert match is not None
    assert "encoding=" not in _call_source(text, match.end() - 1)
