"""Company settings and feature flags (SRS 18, D-001, D-016, D-033 #11)."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import AppError
from app.core.permissions import CompanyContext, scoped
from app.core.settings_registry import (
    ALLOW_LIST_KEYS,
    FEATURE_FLAGS,
    SETTINGS,
    CompanyGroupEntry,
    cross_key_errors,
    parse_allow_list,
    typed,
)
from app.models.config import CompanySetting, FeatureConfig
from app.models.enums import MasterStatus
from app.models.masters import Group
from app.schemas.settings import FlagValue, SettingsOut, SettingsUpdate, SettingValue
from tally_contract.errors import ErrorCode

_CACHE = "settings_overrides"  # session.info key: one session per request = per-request cache


async def _overrides(session: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    cache: dict[uuid.UUID, dict[str, Any]] = session.info.setdefault(_CACHE, {})
    if company_id not in cache:
        rows = await session.execute(
            select(CompanySetting.setting_key, CompanySetting.setting_value).where(
                CompanySetting.company_id == company_id
            )
        )
        cache[company_id] = dict(rows.tuples().all())
    return cache[company_id]


async def get_setting(session: AsyncSession, company_id: uuid.UUID, key: str) -> Any:
    """Effective value (override, else default); DECIMAL settings come back as Decimal."""
    overrides = await _overrides(session, company_id)
    return typed(key, overrides[key] if key in overrides else SETTINGS[key].default)


async def get_flag(session: AsyncSession, company_id: uuid.UUID, name: str) -> bool:
    enabled = (
        await session.execute(
            select(FeatureConfig.enabled).where(
                FeatureConfig.company_id == company_id, FeatureConfig.feature_name == name
            )
        )
    ).scalar_one_or_none()
    return FEATURE_FLAGS[name] if enabled is None else enabled


async def _flags(session: AsyncSession, company_id: uuid.UUID) -> dict[str, bool]:
    rows = await session.execute(
        select(FeatureConfig.feature_name, FeatureConfig.enabled).where(
            FeatureConfig.company_id == company_id
        )
    )
    return dict(rows.tuples().all())


# --- allow-lists: stored by identifier, shown by current name (D-001) -------------------


async def _live_groups(
    session: AsyncSession, ctx: CompanyContext
) -> tuple[dict[str, Group], dict[str, Group]]:
    rows = await session.execute(
        scoped(select(Group), Group, ctx).where(Group.status == MasterStatus.ACTIVE)
    )
    groups = list(rows.scalars())
    by_reserved = {g.reserved_name: g for g in groups if g.reserved_name}
    return by_reserved, {g.tally_guid: g for g in groups}


def _resolve(
    stored: list[dict[str, str]], by_reserved: dict[str, Group], by_guid: dict[str, Group]
) -> list[dict[str, Any]]:
    resolved = []
    for entry in stored:
        name: str | None
        if entry["type"] == "PREDEFINED":
            group = by_reserved.get(entry["reserved_name"])
            name = group.name if group else entry["reserved_name"]
        else:
            group = by_guid.get(entry["tally_guid"])
            name = group.name if group else None
        resolved.append({**entry, "display_name": name, "is_missing": group is None})
    return resolved


def _company_group_error(entry: CompanyGroupEntry, by_guid: dict[str, Group]) -> str | None:
    group = by_guid.get(entry.tally_guid)
    if group is None:  # also another company's GUID: never reveal that it exists (SEC-1.7)
        return f"unknown group {entry.tally_guid!r}"
    if group.is_predefined:
        return f"{group.name!r} is a predefined group: use the PREDEFINED form"
    if group.parent_group_id is not None or group.parent_tally_guid is not None:
        return f"{group.name!r} is a nested group and can never be a classification anchor"
    return None


# --- read and update ------------------------------------------------------------------


async def read_settings(session: AsyncSession, ctx: CompanyContext) -> SettingsOut:
    overrides = await _overrides(session, ctx.company_id)
    by_reserved, by_guid = await _live_groups(session, ctx)
    settings: dict[str, SettingValue] = {}
    for key, spec in SETTINGS.items():
        value = overrides.get(key, spec.default)
        if key in ALLOW_LIST_KEYS:
            value = _resolve(value, by_reserved, by_guid)
        settings[key] = SettingValue(value=value, is_default=key not in overrides)
    flags = await _flags(session, ctx.company_id)
    return SettingsOut(
        settings=settings,
        feature_flags={
            name: FlagValue(enabled=flags.get(name, default), is_default=name not in flags)
            for name, default in FEATURE_FLAGS.items()
        },
    )


async def update_settings(
    session: AsyncSession, ctx: CompanyContext, body: SettingsUpdate
) -> SettingsOut:
    """Validates every value first; writes nothing unless all of them pass."""
    errors: dict[str, str] = {}
    new: dict[str, Any] = {}
    _, by_guid = await _live_groups(session, ctx)
    for key, raw in body.settings.items():
        spec = SETTINGS.get(key)
        if spec is None:
            errors[key] = "unknown setting"
            continue
        try:
            new[key] = spec.validate(raw)
        except ValueError as exc:
            errors[key] = str(exc)
            continue
        if key in ALLOW_LIST_KEYS:
            problems = [
                problem
                for entry in parse_allow_list(raw)
                if isinstance(entry, CompanyGroupEntry)
                and (problem := _company_group_error(entry, by_guid))
            ]
            if problems:
                errors[key] = problems[0]
    for name in body.feature_flags:
        if name not in FEATURE_FLAGS:
            errors[name] = "unknown feature flag"
    overrides = await _overrides(session, ctx.company_id)
    if not errors:
        effective = {k: overrides.get(k, s.default) for k, s in SETTINGS.items()} | new
        errors = cross_key_errors(effective)
    if errors:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Invalid settings",
            422,
            {"errors": [{"key": k, "message": m} for k, m in errors.items()]},
        )

    for key, value in new.items():
        before = overrides.get(key, SETTINGS[key].default)
        if before == value:
            continue
        await session.execute(
            insert(CompanySetting)
            .values(
                company_id=ctx.company_id,
                setting_key=key,
                setting_value=value,
                data_type=SETTINGS[key].data_type,
                updated_by=ctx.user_id,
            )
            .on_conflict_do_update(
                index_elements=[CompanySetting.company_id, CompanySetting.setting_key],
                set_={"setting_value": value, "updated_by": ctx.user_id, "updated_at": func.now()},
            )
        )
        await audit.record(
            session,
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            action="SETTING_CHANGED",
            entity_type="company_setting",
            entity_id=key,
            before={"value": before},
            after={"value": value},
        )
    flags = await _flags(session, ctx.company_id)
    for name, enabled in body.feature_flags.items():
        before_flag = flags.get(name, FEATURE_FLAGS[name])
        if before_flag == enabled:
            continue
        await session.execute(
            insert(FeatureConfig)
            .values(
                company_id=ctx.company_id,
                feature_name=name,
                enabled=enabled,
                updated_by=ctx.user_id,
            )
            .on_conflict_do_update(
                index_elements=[FeatureConfig.company_id, FeatureConfig.feature_name],
                set_={"enabled": enabled, "updated_by": ctx.user_id, "updated_at": func.now()},
            )
        )
        await audit.record(
            session,
            company_id=ctx.company_id,
            user_id=ctx.user_id,
            action="FEATURE_FLAG_CHANGED",
            entity_type="feature_config",
            entity_id=name,
            before={"enabled": before_flag},
            after={"enabled": enabled},
        )
    session.info.get(_CACHE, {}).pop(ctx.company_id, None)
    await session.commit()
    return await read_settings(session, ctx)
