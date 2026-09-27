"""Contract fixtures (TEST-1.1..1.4): XML in, expected parse result out.

Each `fixtures/xml/synthetic/<case>.xml` has `<case>.expected.json`:
    {"parse": "collection:VOUCHER" | "keys" | "info" | "stock_closing" | "ledger_closing",
     "udf": [<UdfMapping>, ...],            # optional
     "expected": {records, errors, document_error, invalid_characters_removed}}
Live captures (`fixtures/xml/live/**/<id>.response.xml`) join once step G-E adds their
`<id>.response.expected.json`.

    uv run python -m tally_tools.fixtures update           # show what would change; exit 1
    uv run python -m tally_tools.fixtures update --force   # rewrite "expected"; review the diff
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tally_contract.enums import CollectionType
from tally_contract.parser import (
    ParseResult,
    parse_collection,
    parse_info,
    parse_keys,
    parse_ledger_closing,
    parse_stock_closing,
)
from tally_contract.udf import UdfMapping, UdfReader

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "fixtures" / "xml"
SYNTHETIC = FIXTURES / "synthetic"
LIVE = FIXTURES / "live"


def expected_path(xml: Path) -> Path:
    return xml.with_name(f"{xml.stem}.expected.json")


def cases() -> list[Path]:
    """Every fixture XML that is a test case: all synthetic ones, and live responses that have
    been given an expected file."""
    synthetic = sorted(SYNTHETIC.glob("*.xml"))
    live = sorted(p for p in LIVE.rglob("*.response.xml") if expected_path(p).is_file())
    return synthetic + live


def load_spec(xml: Path) -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(expected_path(xml).read_text(encoding="utf-8"))
    return spec


def parse_fixture(xml: Path, spec: dict[str, Any]) -> ParseResult[Any]:
    raw = xml.read_bytes()
    kind: str = spec["parse"]
    if kind.startswith("collection:"):
        mappings = [UdfMapping.model_validate(m) for m in spec.get("udf", [])]
        reader = UdfReader(mappings) if mappings else None
        return parse_collection(raw, CollectionType(kind.split(":", 1)[1]), reader)
    parsers: dict[str, Any] = {
        "keys": parse_keys,
        "info": parse_info,
        "stock_closing": parse_stock_closing,
        "ledger_closing": parse_ledger_closing,
    }
    result: ParseResult[Any] = parsers[kind](raw)
    return result


def as_json(result: ParseResult[Any]) -> dict[str, Any]:
    """The parse result as plain JSON (Decimals and dates as strings)."""
    plain: dict[str, Any] = json.loads(
        json.dumps(
            {
                "records": [r.model_dump(mode="json") for r in result.records],
                "errors": [e.model_dump(mode="json") for e in result.errors],
                "document_error": (
                    result.document_error.model_dump(mode="json") if result.document_error else None
                ),
                "invalid_characters_removed": result.invalid_characters_removed,
            }
        )
    )
    return plain


def update(force: bool) -> list[str]:
    """Names of fixtures whose expected result differs; rewritten only with force."""
    changed = []
    for xml in cases():
        spec = load_spec(xml)
        actual = as_json(parse_fixture(xml, spec))
        if spec.get("expected") != actual:
            changed.append(xml.relative_to(ROOT).as_posix())
            if force:
                spec["expected"] = actual
                expected_path(xml).write_text(
                    json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tally_tools.fixtures")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("update")
    up.add_argument("--force", action="store_true", help="rewrite expected results")
    args = parser.parse_args(argv)
    changed = update(args.force)
    for name in changed:
        sys.stdout.write(f"{'updated' if args.force else 'would change'}: {name}\n")
    if changed and not args.force:
        sys.stdout.write("Nothing written. Rerun with FORCE=1 and review the diff.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
