"""The backend's OpenAPI document, for the frontend's generated types (P13.1, D-018).

    uv run python -m tally_tools.openapi            # rewrite frontend/src/api/openapi.json
Then `cd frontend && npm run gen:api` turns it into src/api/schema.d.ts. A test fails when the
committed document no longer matches the backend.
"""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
OUT = ROOT / "frontend" / "src" / "api" / "openapi.json"


def document() -> dict[str, Any]:
    from app.main import create_app

    spec: dict[str, Any] = create_app().openapi()
    return spec


def render() -> str:
    return json.dumps(document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
