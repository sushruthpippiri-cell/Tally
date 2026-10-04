"""P8.1 / P8.9: architecture guards (D-044 #1, #4), written before the metrics so they start
constrained. Each guard is a function over {path: source} and is also run on a bad source, so
the guard itself is proven to fail (the mutation check stays in the suite)."""

import ast
from pathlib import Path

import pytest

import app
from app.analytics import query

APP = Path(app.__file__).parent

# AC-34 / ACC-DATA-1: these packages never read amount_raw.
NO_RAW_AMOUNT = ("analytics/", "exports/", "reconciliation/", "anomaly/")
# The tables whose rows carry money. Only these modules may import them, so a dashboard,
# drill-down or export can reach a figure only through app.analytics.query (ACC-4.4).
MONEY_TABLES = {"VoucherEntry", "BillAllocation", "CostCentreAllocation", "VoucherItem"}
MONEY_TABLE_MODULES = (
    "models/",
    "sync/",
    "analytics/blocks.py",
    "analytics/returns.py",
    "analytics/metrics/",
    "services/vouchers.py",  # voucher detail: display only (P14.1)
)
METRICS_DIR = "analytics/metrics/"


def _app_sources() -> dict[str, str]:
    return {p.relative_to(APP).as_posix(): p.read_text(encoding="utf-8") for p in APP.rglob("*.py")}


def raw_amount_reads(sources: dict[str, str]) -> list[str]:
    found = []
    for path, src in sources.items():
        if not path.startswith(NO_RAW_AMOUNT):
            continue
        for node in ast.walk(ast.parse(src)):
            name = (
                node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else node.value
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                else node.name
                if isinstance(node, ast.alias)
                else ""
            )
            if "amount_raw" in name:
                found.append(f"{path}:{node.lineno if hasattr(node, 'lineno') else '?'}")
    return found


def money_table_imports(sources: dict[str, str]) -> list[str]:
    found = []
    for path, src in sources.items():
        if path.startswith(MONEY_TABLE_MODULES):
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom):
                found += [f"{path}: {a.name}" for a in node.names if a.name in MONEY_TABLES]
            if isinstance(node, ast.Attribute) and node.attr in MONEY_TABLES:
                found.append(f"{path}: {node.attr}")
    return found


def detail_query_callers(sources: dict[str, str]) -> list[str]:
    """Only app/analytics/query.py turns a detail query into a figure."""
    return [
        f"{path}:{node.lineno}"
        for path, src in sources.items()
        if path != "analytics/query.py"
        for node in ast.walk(ast.parse(src))
        if (isinstance(node, ast.Attribute) and node.attr == "detail_query")
        or (isinstance(node, ast.Name) and node.id == "detail_query")
    ]


def _calls_select(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == "select")
            or (isinstance(n.func, ast.Attribute) and n.func.attr == "select")
        )
        for n in ast.walk(node)
    )


def metric_module_problems(sources: dict[str, str]) -> list[str]:
    """A metric module has exactly one public function, `detail_query`; builds its query
    nowhere else; and runs nothing (no async code, so no session)."""
    problems = []
    for path, src in sources.items():
        if not path.startswith(METRICS_DIR) or path.endswith("__init__.py"):
            continue
        tree = ast.parse(src)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        public = [f.name for f in functions if not f.name.startswith("_")]
        if public != ["detail_query"]:
            problems.append(f"{path}: public functions {public}, expected ['detail_query']")
        for node in tree.body:
            is_detail = isinstance(node, ast.FunctionDef) and node.name == "detail_query"
            if not is_detail and _calls_select(node):
                problems.append(f"{path}:{node.lineno}: select() outside detail_query")
        if any(isinstance(n, ast.AsyncFunctionDef | ast.Await) for n in ast.walk(tree)):
            problems.append(f"{path}: runs queries itself")
    return problems


def _registered_modules() -> set[str]:
    return {f"{METRICS_DIR}{m.__name__.rsplit('.', 1)[1]}.py" for m in query.METRICS.values()}


# --- the real code ------------------------------------------------------------------------


@pytest.mark.req_partial("AC-34")  # the parse half: shared/tests/test_parser_acceptance.py
@pytest.mark.req("ACC-DATA-1")
def test_no_analytics_query_reads_amount_raw() -> None:
    assert raw_amount_reads(_app_sources()) == []


@pytest.mark.req_partial("ACC-4.4")  # the API and exports: tests/api/test_exports.py
def test_every_metric_has_one_query_path() -> None:
    sources = _app_sources()
    assert metric_module_problems(sources) == []
    assert detail_query_callers(sources) == []
    assert money_table_imports(sources) == []
    metric_files = {p for p in sources if p.startswith(METRICS_DIR) and "__init__" not in p}
    assert _registered_modules() == metric_files  # every metric is reachable, and only those


# --- the guards themselves fail on bad code (mutation checks) -----------------------------


@pytest.mark.parametrize(
    "src",
    [
        "x = E.amount_raw",
        "from app.models.vouchers import amount_raw",
        "q = text('select sum(amount_raw::numeric) from voucher_entries')",
        "c = getattr(VoucherEntry, 'amount_raw')",
    ],
)
def test_the_amount_raw_guard_catches(src: str) -> None:
    assert raw_amount_reads({"analytics/metrics/sales.py": src})
    assert raw_amount_reads({"exports/csv.py": src})
    assert not raw_amount_reads({"sync/vouchers.py": src})  # the parser side may write it


GOOD_METRIC = "def detail_query(ctx):\n    return select(x)\n\ndef _helper(c):\n    return c + 1\n"


@pytest.mark.parametrize(
    "src",
    [
        GOOD_METRIC + "def total_sales(ctx):\n    return 1\n",  # a second public function
        GOOD_METRIC + "def _rows(ctx):\n    return select(y)\n",  # a second query
        GOOD_METRIC + "SUMMARY = select(z)\n",
        GOOD_METRIC + "async def _run(session):\n    return await session.execute(q)\n",
        "def build(ctx):\n    return select(x)\n",  # no detail_query at all
    ],
)
def test_the_one_query_path_guard_catches(src: str) -> None:
    assert metric_module_problems({"analytics/metrics/sales.py": src})
    assert metric_module_problems({"analytics/metrics/sales.py": GOOD_METRIC}) == []


def test_the_caller_and_table_guards_catch() -> None:
    dashboard = (
        "from app.models.vouchers import VoucherEntry\n"
        "from app.analytics.metrics import sales\n"
        "rows = sales.detail_query(ctx)\n"
    )
    assert detail_query_callers({"api/analytics.py": dashboard}) == ["api/analytics.py:3"]
    assert money_table_imports({"exports/csv.py": dashboard}) == ["exports/csv.py: VoucherEntry"]
    assert money_table_imports({"services/x.py": "q = select(models.VoucherItem)"})
    assert detail_query_callers({"analytics/query.py": dashboard}) == []
