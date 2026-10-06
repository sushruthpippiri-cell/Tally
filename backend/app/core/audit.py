"""The only writer of audit_logs (SEC-1.13). Records every LOG-1.2 field; user_id None = system."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.config import AuditLog
from tally_contract.errors import ErrorCode

JSON = dict[str, Any]

# Every action that may be written, grouped by the LOG-1.1 clause it answers (P16.3). An action
# not listed here is refused, so a new audited event has to be classified against the SRS - and
# `tests/core/test_audit_actions.py` fails if a clause ends up with no action at all.
ACTIONS: dict[str, frozenset[str]] = {
    "login": frozenset({"LOGIN", "REFRESH_TOKEN_REUSE"}),
    "sync requests": frozenset({"SYNC_REQUESTED", "RECONCILIATION_QUEUED"}),
    "schedule changes": frozenset(
        {"SCHEDULE_CREATED", "SCHEDULE_UPDATED", "SCHEDULE_ACTIVATED", "SCHEDULE_DEACTIVATED"}
    ),
    "Agent registration/rotation/revocation": frozenset(
        {
            "REGISTRATION_TOKEN_CREATED",
            "AGENT_REGISTERED",
            "AGENT_REGISTRATION_REJECTED",
            "AGENT_CREDENTIAL_ROTATED",
            "AGENT_REVOKED",
            "AGENT_TALLY_SETTINGS_CHANGED",
        }
    ),
    "setting and feature-flag changes": frozenset(
        {"SETTING_CHANGED", "FEATURE_FLAG_CHANGED", "CUSTOM_FIELDS_UPDATED", "COMPANY_UPDATED"}
    ),
    # USER_ATTACHED: an existing user given a role in a second company, rather than created.
    "user and role changes": frozenset(
        {"USER_CREATED", "USER_ATTACHED", "ROLES_CHANGED", "PASSWORD_CHANGED"}
    ),
    "anomaly reviews": frozenset({"ANOMALY_REVIEWED"}),
    "exports": frozenset({"EXPORT"}),
    # "system changes to vouchers and masters (modifications, cancellations, missing and
    # reappeared records)". VOUCHER_MODIFIED/VOUCHER_CANCELLED are chosen in one expression in
    # app/sync/vouchers.py, so a grep for `action="` does not find them.
    "system changes to vouchers and masters": frozenset(
        {
            "VOUCHER_MODIFIED",
            "VOUCHER_CANCELLED",
            "MISSING_IN_TALLY",
            "REAPPEARED",
            "KEY_LIST_CONFIRMED",
            # A master's resolved group or base voucher type changing is a system change to a
            # master, and it moves figures between metrics - passed positionally from
            # app/sync/hierarchy.py.
            "GROUP_RESOLUTION_CHANGED",
            "VOUCHER_TYPE_RESOLUTION_CHANGED",
        }
    ),
    # Not named by LOG-1.1, but the same kind of event and worth the trail.
    "other": frozenset({"COMPANY_CREATED"}),
}
KNOWN_ACTIONS: frozenset[str] = frozenset().union(*ACTIONS.values())


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
    if action not in KNOWN_ACTIONS:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"Unregistered audit action {action!r}: add it to audit.ACTIONS under the LOG-1.1 "
            "clause it belongs to",
            500,
        )
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
