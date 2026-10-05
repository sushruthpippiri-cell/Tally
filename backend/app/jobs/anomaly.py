"""The two anomaly jobs (P15.1, D-055 #4). Neither does anything for a company whose feature
flag is off, and the explainer is imported only when there is something to explain - so with the
flag off nothing in `app.anomaly` that touches `anthropic` or `mcp` is even loaded (AC-55).

The rules follow a cursor rather than hooking the sync path: `app.sync` may not import
`app.anomaly` (import-linter), and running rules inside `close_run` would hold the Agent's
request transaction. A sync's new data is scanned within a minute of landing.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.config import FeatureConfig
from app.services import anomaly
from tally_contract.log import get_logger

log = get_logger(__name__)

#: D-055 #3: the configured model id is checked once per process, the first time there is
#: actually something to explain. A typo would otherwise make every explanation unavailable with
#: nothing to say why.
_model_checked = False


async def _enabled_companies(session: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    """(company_id, timezone) for companies with the flag on. The registry default is off, so
    only an explicit override counts - one query, and none when nobody has enabled it."""
    rows = await session.execute(
        select(Company.company_id, Company.company_timezone)
        .join(FeatureConfig, FeatureConfig.company_id == Company.company_id)
        .where(FeatureConfig.feature_name == anomaly.FEATURE, FeatureConfig.enabled.is_(True))
    )
    return [(r.company_id, r.company_timezone) for r in rows]


async def anomaly_rules(session: AsyncSession, now: datetime) -> int:
    """Scan every enabled company's newly stored vouchers. Returns flags written plus cleared."""
    changed = 0
    for company_id, _tz in await _enabled_companies(session):
        written, cleared = await anomaly.scan(session, company_id, now)
        if written or cleared:
            log.info("anomaly_scan", company_id=str(company_id), written=written, cleared=cleared)
        changed += written + cleared
    return changed


async def anomaly_explanations(session: AsyncSession, now: datetime) -> int:
    """Ask for an explanation of the newest anomalies still wanting one, within the day's cap.

    Returns early, having imported nothing from the AI SDKs, when the explainer is not
    configured - so the flags stay PENDING and are picked up once a key and model are set,
    rather than burning their retry budget on a failure that is not about availability.
    """
    companies = await _enabled_companies(session)
    if not companies:
        return 0
    from app.core.config import get_settings

    settings = get_settings()
    if settings.anthropic_api_key is None or not settings.anomaly_explainer_model:
        log.info("anomaly_explainer_not_configured")
        return 0

    from app.anomaly import explainer  # imported here: nothing loads anthropic/mcp otherwise

    global _model_checked
    if not _model_checked:
        _model_checked = True
        await explainer.check_model_configured()

    explained = 0
    for company_id, timezone in companies:
        due = await anomaly.due_for_explanation(session, company_id, now, timezone)
        for flag in due:
            names = await anomaly.substitutions(session, flag)
            outcome = await explainer.explain(session, flag, now=now, substitutions=names)
            log.info(
                "anomaly_explanation",
                anomaly_id=flag.id,
                status=outcome.status.value,
                reason=None if outcome.reason is None else outcome.reason.value,
            )
            explained += 1
    return explained
