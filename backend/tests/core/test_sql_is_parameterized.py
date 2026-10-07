"""SEC-1.6 (P16.2): no SQL is built by string formatting in shipped code.

The claim "SQLAlchemy ORM / Core expressions only" was true when written and nothing checked
it. This walks the source so it stays true: a `text()`, `execute()` or `exec_driver_sql()`
whose SQL is an f-string, a `%`/`+` concatenation or a `.format()` fails, even when today's
value happens to be harmless.

Tests and `alembic/versions` are not scanned: they build DDL from hardcoded table names, which
is fine and would only force noise suppressions here.
"""

import ast
from pathlib import Path

import pytest

import app
import tally_agent
import tally_contract

SCANNED = (
    Path(app.__file__).parent,
    Path(tally_agent.__file__).parent,
    Path(tally_contract.__file__).parent,
)
SQL_CALLS = {"text", "execute", "exec_driver_sql", "executemany", "scalar", "scalars"}


def _is_built(node: ast.expr) -> bool:
    """A string produced by formatting rather than written as a literal."""
    if isinstance(node, ast.JoinedStr):  # f"..."
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod | ast.Add):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in {"format", "join"}
    return False


def built_sql(sources: dict[str, str]) -> list[str]:
    found = []
    for path, src in sources.items():
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name not in SQL_CALLS or not node.args:
                continue
            if _is_built(node.args[0]):
                found.append(f"{path}:{node.lineno}")
    return found


def _sources() -> dict[str, str]:
    return {
        f"{root.name}/{p.relative_to(root).as_posix()}": p.read_text(encoding="utf-8")
        for root in SCANNED
        for p in root.rglob("*.py")
    }


@pytest.mark.req("SEC-1.6")
def test_no_shipped_code_builds_sql_by_formatting() -> None:
    assert built_sql(_sources()) == []


@pytest.mark.parametrize(
    "src",
    [
        'session.execute(text(f"SELECT * FROM {table}"))',
        'conn.execute("SELECT * FROM t WHERE id = %s" % ident)',
        'session.execute(text("SELECT * FROM t WHERE name = " + name))',
        'session.execute("SELECT {} FROM t".format(col))',
        'conn.exec_driver_sql(f"TRUNCATE {table}")',
    ],
)
def test_the_guard_catches_built_sql(src: str) -> None:
    assert built_sql({"app/x.py": src})


def test_the_guard_allows_a_literal_with_bind_parameters() -> None:
    good = (
        'session.execute(text("SELECT set_config(\'app.company_id\', :c, false)"), {"c": cid})\n'
        'session.execute(text("SELECT 1"))\n'
        "session.execute(select(Voucher).where(Voucher.company_id == company_id))\n"
    )
    assert built_sql({"app/x.py": good}) == []
