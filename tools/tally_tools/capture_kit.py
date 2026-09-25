"""Build the PowerShell capture kit (D-038) and verify what it captured.

    uv run python -m tally_tools.capture_kit build            # -> dist/tally-capture-kit/ + .zip
    uv run python -m tally_tools.capture_kit verify --captures DIR ...   # CI, against the mock

Request templates are generated from `tally_contract.requests`, so the kit always sends exactly
what the Agent will send; placeholders ({{COMPANY}}, ...) are filled in by the script.
"""

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tally_contract import requests as rq
from tally_contract import tally_constants as tc
from tally_contract.enums import CollectionType as C
from tally_tools.mock_tally import MockConfig, answer

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "tools" / "capture_kit"
KIT_NAME = "tally-capture-kit"
KIT_VERSION = "1"
COMPANY, OTHER, BOOKS_FROM, AS_OF = (
    "{{COMPANY}}",
    "{{OTHER_COMPANY}}",
    "{{BOOKS_FROM}}",
    "{{AS_OF}}",
)
NOT_OPEN_COMPANY = "Company That Is Not Open Ltd"

Build = Callable[[], bytes]


def _full(collection: C, **kw: Any) -> Build:
    return lambda: rq.collection(collection, COMPANY, **kw)


VOUCHER_DATES = {"date_from": BOOKS_FROM, "date_to": tc.FULL_PULL_DATE_TO}

# id -> (request, gates it gives evidence for, needs -OtherCompany)
CAPTURE: dict[str, tuple[Build, list[str], bool]] = {
    "info": (lambda: rq.info(COMPANY), ["G20", "G35"], False),
    "info_other_company": (lambda: rq.info(OTHER), ["G20"], True),
    "company_full": (_full(C.COMPANY), ["G10", "G20", "G33"], False),
    "groups_full": (_full(C.GROUP), ["G5", "G10", "G12", "G13", "G14", "G32"], False),
    "ledgers_full": (_full(C.LEDGER), ["G1", "G5", "G16", "G29", "G31"], False),
    "voucher_types_full": (_full(C.VOUCHER_TYPE), ["G10", "G15", "G32"], False),
    "stock_items_full": (_full(C.STOCK_ITEM), ["G2", "G17", "G27"], False),
    "cost_centres_full": (_full(C.COST_CENTRE), ["G4"], False),
    "vouchers_full": (
        _full(C.VOUCHER, **VOUCHER_DATES),
        ["G3", "G5", "G9", "G23", "G25", "G26", "G27", "G28", "G30", "G31", "G34"],
        False,
    ),
    # G7/G33: the window filter on small pages; compare with the full pulls.
    "ledgers_window_0_10": (_full(C.LEDGER, from_alter_id=0, to_alter_id=10), ["G7"], False),
    "vouchers_window_0_20": (
        _full(C.VOUCHER, from_alter_id=0, to_alter_id=20, **VOUCHER_DATES),
        ["G7", "G33"],
        False,
    ),
    "vouchers_window_20_40": (
        _full(C.VOUCHER, from_alter_id=20, to_alter_id=40, **VOUCHER_DATES),
        ["G7", "G33"],
        False,
    ),
    **{f"{c.value.lower()}_keys": (_full(c, keys_only=True), ["G21"], False) for c in C},
    "stock_closing": (lambda: rq.stock_closing(COMPANY, AS_OF), ["G18"], False),
    "ledger_closing": (lambda: rq.ledger_closing(COMPANY, AS_OF), ["G19", "G23"], False),
    # G35: what Tally says for an unknown report and for a company that is not open.
    "error_unknown_report": (
        lambda: rq.envelope("TA_ReportThatDoesNotExist", {tc.VAR_COMPANY: COMPANY}),
        ["G35"],
        False,
    ),
    "error_company_not_open": (lambda: rq.info(NOT_OPEN_COMPANY), ["G35"], False),
}
CHECK: dict[str, Build] = {
    "company_list": rq.builtin_company_list,
    "info": lambda: rq.info(COMPANY),
}


def _builtin(name: str) -> Build:
    return lambda: rq.builtin_report(name, COMPANY, BOOKS_FROM, AS_OF)


REFERENCE: dict[str, Build] = {
    name.lower().replace(" ", "_"): _builtin(name) for name in tc.BUILTIN_REFERENCE_REPORTS
}

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "G8",
        "gates": ["G6", "G8", "G24"],
        "requests": ["vouchers_full", "voucher_keys"],
        "instructions": [
            "Open one Sales voucher (Alt+G > Voucher, or Day Book > Enter), change its amount",
            "and its narration, and save it (Ctrl+A). Note its voucher number.",
        ],
        "undo": "",
    },
    {
        "name": "G9",
        "gates": ["G6", "G9"],
        "requests": ["vouchers_full", "voucher_keys"],
        "instructions": [
            "Cancel one voucher: open it in alteration and choose Cancel Vch (Alt+X);",
            "confirm. Note its voucher number.",
        ],
        "undo": "",
    },
    {
        "name": "G11",
        "gates": ["G11"],
        "requests": ["vouchers_full", "voucher_keys", "ledger_keys"],
        "instructions": [
            "Delete one voucher: open it in alteration and choose Delete (Alt+D); confirm.",
            "Note its voucher number.",
        ],
        "undo": "",
    },
    {
        "name": "G29",
        "gates": ["G29"],
        "requests": ["ledgers_full", "stock_items_full", "ledger_keys"],
        "instructions": [
            "If TallyPrime lets you mark a ledger or stock item as inactive/deactivated, do",
            "that to one ledger. If there is no such option, change nothing and say so.",
        ],
        "undo": "",
    },
    {
        "name": "G32",
        "gates": ["G32"],
        "requests": ["groups_full", "voucher_types_full"],
        "instructions": [
            "Rename the predefined group 'Sundry Debtors' to 'Customers' (Alt+G > Alter >",
            "Group > Sundry Debtors > Name), and the voucher type 'Sales' to 'Sales Invoice'.",
        ],
        "undo": "Rename them back to 'Sundry Debtors' and 'Sales'.",
    },
    {
        "name": "ACC-7.5",
        "gates": ["G12", "G13"],
        "requests": ["groups_full", "ledgers_full"],
        "instructions": [
            "Move the group 'Retail Customers' to a different parent: alter the group and",
            "change 'Under' from 'Sundry Debtors' to 'Current Assets'.",
        ],
        "undo": "Move it back under 'Sundry Debtors'.",
    },
    {
        "name": "AGT-5.4",
        "gates": ["G20", "G35"],
        "requests": ["info", "company_full"],
        "instructions": [
            "Rename the company (Alt+K > Alter > your company > Company Name), add ' Renamed'.",
            "Keep using the OLD name with -Company: the AFTER capture must show the failure.",
        ],
        "undo": "Rename the company back to its original name.",
    },
]

# Gates that need analysis or setup rather than their own request (still on the checklist).
CHECKLIST_ONLY: dict[str, str] = {
    "G13": "Analyse groups_full: every chain reaches a predefined group.",
    "G22": "Needs a user-defined field in the test company and the generated UDF include (P4.6).",
    "G24": "Analyse the G8 scenario: is there any stable line identifier to add to the TDL?",
    "G28": "Compare product-line totals in vouchers_full with the Trial Balance reference.",
}


def manifest() -> dict[str, Any]:
    def entries(builds: dict[str, Any], folder: str) -> list[dict[str, Any]]:
        out = []
        for key, value in builds.items():
            gates, needs_other = (value[1], value[2]) if isinstance(value, tuple) else ([], False)
            out.append(
                {
                    "id": key,
                    "file": f"requests/{folder}/{key}.xml",
                    "gates": gates,
                    "needs_other_company": needs_other,
                    # G35 evidence: Tally is meant to answer these with an error.
                    "expect_error": key.startswith("error_"),
                }
            )
        return out

    return {
        "kit_version": KIT_VERSION,
        "tdl_version": tc.TDL_VERSION,
        "content_type": tc.REQUEST_CONTENT_TYPE,
        "server_running_text": tc.SERVER_RUNNING_TEXT,
        "report_not_found_markers": list(tc.REPORT_NOT_FOUND_MARKERS),
        "company_not_loaded_markers": list(tc.COMPANY_NOT_LOADED_MARKERS),
        "check": entries(CHECK, "check"),
        "capture": entries(CAPTURE, "capture"),
        "reference": [e | {"gates": ["TEST-4.1"]} for e in entries(REFERENCE, "reference")],
        "scenarios": SCENARIOS,
        "checklist_only": CHECKLIST_ONLY,
    }


def gates_covered(m: dict[str, Any]) -> set[str]:
    covered = {g for e in m["capture"] for g in e["gates"]}
    covered |= {g for s in m["scenarios"] for g in s["gates"]}
    return covered | set(m["checklist_only"])


def build(out: Path) -> Path:
    kit = out / KIT_NAME
    if kit.exists():
        shutil.rmtree(kit)
    for folder, builds in (("check", CHECK), ("capture", CAPTURE), ("reference", REFERENCE)):
        (kit / "requests" / folder).mkdir(parents=True)
        for key, value in builds.items():
            request = value[0] if isinstance(value, tuple) else value
            (kit / "requests" / folder / f"{key}.xml").write_bytes(request())
    (kit / "manifest.json").write_text(
        json.dumps(manifest(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for name in ("Capture-Tally.ps1", "README.md", "CHECKLIST.md"):
        shutil.copy2(SOURCE / name, kit / name)
    (kit / "tdl").mkdir()
    for name in ("TA_Minimal.tdl", "TallyAnalytics.tdl"):
        shutil.copy2(ROOT / "tdl" / name, kit / "tdl" / name)
    shutil.make_archive(str(out / KIT_NAME), "zip", root_dir=out, base_dir=KIT_NAME)
    return kit


# --- verification against the mock (CI) ----------------------------------------------------


def _runs(captures: Path, step: str) -> list[Path]:
    return sorted(p for p in captures.iterdir() if p.is_dir() and p.name.endswith(f"-{step}"))


def verify(captures: Path, config: MockConfig, expect_check_ok: bool = True) -> list[str]:
    """Problems found (empty = good). Every saved response must equal, byte for byte, what the
    mock sent for the saved request; failures must be recorded, not lost."""
    problems: list[str] = []
    for run in [
        *_runs(captures, "all"),
        *_runs(captures, "capture"),
        *(p for p in captures.glob("*-scenario-*") if p.is_dir()),
    ]:
        for required in ("run.json", "summary.json"):
            if not (run / required).is_file():
                problems.append(f"{run.name}: {required} missing")
        if not (run.parent / f"{run.name}.zip").is_file():
            problems.append(f"{run.name}: zip missing")
        for meta_file in run.rglob("*.meta.json"):
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            request_file = meta_file.with_name(f"{meta['id']}.request.xml")
            response_file = meta_file.with_name(f"{meta['id']}.response.xml")
            if not request_file.is_file():
                continue  # the GET to the server root has no request body
            status, expected = answer(config, request_file.read_bytes())
            got = response_file.read_bytes() if response_file.is_file() else b""
            if got != expected:
                problems.append(f"{meta_file}: response bytes differ from what Tally sent")
            if meta["http_status"] != status:
                problems.append(f"{meta_file}: status {meta['http_status']} != {status}")
            if meta.get("expected_error") and not meta["ok"]:
                problems.append(f"{meta_file}: the expected Tally error was not recognised")
    for run in _runs(captures, "all") + _runs(captures, "check"):
        check = json.loads((run / "check.json").read_text(encoding="utf-8"))
        if bool(check["ok"]) != expect_check_ok:
            problems.append(f"{run.name}: check ok={check['ok']}, expected {expect_check_ok}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.capture_kit")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, default=ROOT / "dist")
    v = sub.add_parser("verify")
    v.add_argument("--captures", type=Path, required=True)
    v.add_argument("--company", action="append", default=[])
    v.add_argument("--fail-report", action="append", default=[])
    v.add_argument("--no-tdl", action="store_true")
    v.add_argument("--utf16", action="store_true")
    v.add_argument("--expect-check-failed", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "build":
        kit = build(args.out)
        sys.stdout.write(f"built {kit} and {kit}.zip\n")
        return 0
    config = MockConfig(
        companies=args.company or ["Test Co"],
        tdl_loaded=not args.no_tdl,
        fail_reports=set(args.fail_report),
        utf16=args.utf16,
    )
    problems = verify(args.captures, config, expect_check_ok=not args.expect_check_failed)
    for problem in problems:
        sys.stdout.write(f"PROBLEM: {problem}\n")
    sys.stdout.write("capture kit output verified\n" if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
