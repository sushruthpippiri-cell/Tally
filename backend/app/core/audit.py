"""The only writer of audit_logs (SEC-1.13). Records every LOG-1.2 field; user_id None = system."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import AuditLog

JSON = dict[str, Any]


async def record(
    session: AsyncSession,
    *,
    company_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before: JSON | None = None,
    after: JSON | None = None,
    data_range: JSON | None = None,
    result: str = "SUCCESS",
) -> None:
    """Adds the row to the caller's transaction; the caller commits."""
    session.add(
        AuditLog(
            company_id=company_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_value=before,
            after_value=after,
            data_range=data_range,
            result=result,
        )
    )
    await session.flush()


def diff(before: JSON, after: JSON) -> tuple[JSON, JSON]:
    """Only the keys whose value changed, as (before, after)."""
    keys = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k)]
    return (
        {k: before[k] for k in sorted(keys) if k in before},
        {k: after[k] for k in sorted(keys) if k in after},
    )
