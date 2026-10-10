"""P16.5: the load profile requests what the home view requests, and nothing else.

The first harness timed a twelve-call set that the home view never makes - cash flow, expenses,
purchases, rankings and `product_difference` - and reported 6.8 s for a page no user opens. A
performance figure is only as good as the profile behind it, so the profile is pinned to the
source of truth: FR-4.1 in the SRS, and `HomePage.tsx` / `CompanyLayout.tsx` in the frontend.
"""

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
HOME = (ROOT / "frontend/src/pages/HomePage.tsx").read_text(encoding="utf-8")
LAYOUT = (ROOT / "frontend/src/pages/CompanyLayout.tsx").read_text(encoding="utf-8")
LOCUSTFILE = ROOT / "tools/tally_tools/loadtest/locustfile.py"


def _constants() -> SimpleNamespace:
    """The profile's module-level constants, read from the source **without importing it**.

    Importing locustfile.py imports Locust, whose first act is `gevent.monkey.patch_all()`. That
    replaces threading, socket and time for the whole pytest process - and the end-to-end tests
    run the Agent's uploader on a real thread over real sockets, so with gevent loaded the first
    of them hangs until killed. The first version of this test imported the module and did
    exactly that: it passed alone and in every directory that does not use threads, and stalled
    `make check` for twenty minutes. Reading the literals with `ast` needs nothing from Locust.
    """
    values: dict[str, Any] = {}
    for node in ast.parse(LOCUSTFILE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass  # computed from the environment (EMAIL, PERIOD, ...): not a constant
    return SimpleNamespace(**values)


locustfile = _constants()


def _frontend_analytics() -> set[str]:
    """Analytics paths the home page's FIGURES table asks for."""
    block = re.search(r"const FIGURES[^=]*=\s*\[(.*?)\n\];", HOME, re.S)
    assert block, "HomePage.tsx no longer defines FIGURES"
    return set(re.findall(r'\["([a-z-]+)",\s*"', block.group(1)))


@pytest.mark.req("PERF-1.1")
def test_the_profile_requests_the_figures_the_home_page_requests() -> None:
    assert set(locustfile.HOME_ANALYTICS) == _frontend_analytics()


def test_the_profile_includes_sync_status_and_agents() -> None:
    for path in locustfile.HOME_OTHER:
        assert f'"{path}"' in HOME or f"`{path}`" in HOME or path in HOME, path


def test_this_module_does_not_import_locust() -> None:
    """Importing Locust monkey-patches the process with gevent and hangs every threaded test
    that runs after it (see _constants). Guard against the import coming back."""
    import sys

    assert "gevent" not in sys.modules or "locust" not in sys.modules, (
        "locust was imported into the pytest process"
    )
    assert not re.search(
        r"^\s*(import|from)\s+locust", Path(__file__).read_text(encoding="utf-8"), re.M
    )


def test_the_layouts_availability_probe_is_in_the_profile() -> None:
    """CompanyLayout asks payment-behaviour on every company page (FR-PAY-6). Cheap while gate
    G25 has not passed, real work on every page load once it does - so it belongs in the figure."""
    assert "/analytics/payment-behaviour" in LAYOUT
    assert locustfile.LAYOUT_PROBE == ("payment-behaviour",)


@pytest.mark.req("PERF-1.1")
def test_product_difference_is_not_on_the_home_view() -> None:
    """It is a data-quality figure, not a headline (FR-4.1 lists six things and it is not one),
    and on the SRS 17.2 dataset it is the most expensive single figure there is. It loads when
    its own section opens - frontend/src/pages/home.test.tsx asserts the same from the other
    side."""
    requested = {
        *locustfile.HOME_ANALYTICS,
        *locustfile.LAYOUT_PROBE,
        *(p.strip("/") for p in locustfile.HOME_OTHER),
    }
    assert not any("product" in path for path in requested), requested
    assert "product-difference" not in HOME and "product-difference" not in LAYOUT


def test_the_realistic_profile_has_think_time_and_the_stress_profile_does_not() -> None:
    """Ten users opening the page back to back is a capacity test, not ten users using the
    product. The owner's figure for reading time is 5-15 s."""
    assert locustfile.THINK == (5, 15)
    source = LOCUSTFILE.read_text(encoding="utf-8")
    assert 'wait_time = constant(0) if PROFILE == "stress" else between(*THINK)' in source
