from typing import Any, Literal

from pydantic import BaseModel


class CheckSummary(BaseModel):
    check_id: str
    title: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    how_to_fix: str
    count: int


class CheckItems(CheckSummary):
    items: list[dict[str, Any]]
    limit: int
    offset: int
