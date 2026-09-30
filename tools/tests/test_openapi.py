"""P13.1: the frontend's committed OpenAPI document matches the backend (its generated types
are never hand-written, and never stale)."""

from tally_tools import openapi


def test_the_committed_openapi_document_is_current() -> None:
    assert openapi.OUT.is_file(), "run `uv run python -m tally_tools.openapi`"
    assert openapi.OUT.read_text(encoding="utf-8") == openapi.render(), (
        "the API changed: run `uv run python -m tally_tools.openapi` and `npm run gen:api`"
    )
