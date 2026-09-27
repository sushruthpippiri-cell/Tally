"""Custom field (UDF) mappings and the TDL generated from them (DR-UDF-1, DR-UDF-4, P4.6)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.permissions import CompanyContext, scoped
from app.models.config import CustomFieldMapping
from app.schemas.settings import CustomFieldsUpdate
from tally_contract.udf import UdfMapping, generate_tdl


def _mapping(row: CustomFieldMapping) -> UdfMapping:
    return UdfMapping.model_validate(
        {
            "collection_type": row.collection_type,
            "tally_field": row.tally_field,
            "field_key": row.field_key,
            "data_type": row.data_type,
        }
    )


async def list_mappings(session: AsyncSession, ctx: CompanyContext) -> list[UdfMapping]:
    rows = await session.execute(
        scoped(select(CustomFieldMapping), CustomFieldMapping, ctx)
        .where(CustomFieldMapping.is_active)
        .order_by(CustomFieldMapping.collection_type, CustomFieldMapping.field_key)
    )
    return [_mapping(r) for r in rows.scalars()]


async def replace_mappings(
    session: AsyncSession, ctx: CompanyContext, body: CustomFieldsUpdate
) -> list[UdfMapping]:
    before = await list_mappings(session, ctx)
    rows = {
        (r.collection_type, r.field_key): r
        for r in (
            await session.execute(scoped(select(CustomFieldMapping), CustomFieldMapping, ctx))
        ).scalars()
    }
    wanted = {(m.collection_type.value, m.field_key): m for m in body.mappings}
    now = datetime.now(UTC)
    for existing, row in rows.items():
        if existing not in wanted and row.is_active:
            row.is_active, row.updated_by, row.updated_at = False, ctx.user_id, now
    for (collection, field_key), m in wanted.items():
        found = rows.get((collection, field_key))
        if found is None:
            found = CustomFieldMapping(
                company_id=ctx.company_id, collection_type=collection, field_key=field_key
            )
            session.add(found)
        found.tally_field, found.data_type, found.is_active = m.tally_field, m.data_type.value, True
        found.updated_by, found.updated_at = ctx.user_id, now
    await session.flush()
    after = await list_mappings(session, ctx)
    await audit.record(
        session,
        company_id=ctx.company_id,
        user_id=ctx.user_id,
        action="CUSTOM_FIELDS_UPDATED",
        entity_type="custom_field_mappings",
        before={"mappings": [m.model_dump(mode="json") for m in before]},
        after={"mappings": [m.model_dump(mode="json") for m in after]},
    )
    await session.commit()
    return after


async def tdl(session: AsyncSession, ctx: CompanyContext) -> str:
    """DR-UDF-4: generated from the mappings, never edited by hand."""
    return generate_tdl(await list_mappings(session, ctx))
