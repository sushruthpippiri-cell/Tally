"""P15.5 / P15.7: the API, the two jobs, and AC-55 to AC-58 end to end."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomaly import redact
from app.jobs import anomaly as anomaly_jobs
from app.models.company import User
from app.models.config import AiToolLog, AnomalyFlag, AnomalyScanState, FeatureConfig
from app.models.enums import AnomalyRule, ExplanationStatus, RoleName, VoucherStatus
from app.models.vouchers import Voucher
from app.services import anomaly as anomaly_service
from tally_contract.testing import assert_logged
from tests.analytics.books import Books, make_books
from tests.factories import auth_header, make_user

NOW = datetime(2026, 3, 16, 12, tzinfo=UTC)
START = date(2026, 3, 1)


@pytest.fixture
async def books(session: AsyncSession) -> Books:
    return await make_books(session)


@pytest.fixture
async def owner(session: AsyncSession, books: Books) -> User:
    return await make_user(session, books.company, RoleName.OWNER)


async def enable(books: Books) -> None:
    books.session.add(
        FeatureConfig(
            company_id=books.company.company_id,
            feature_name=anomaly_service.FEATURE,
            enabled=True,
        )
    )
    await books.session.flush()


async def sale(books: Books, day: date, amount: str, party: str = "Customer A") -> uuid.UUID:
    v = await books.voucher("Sales", day, [(party, "DEBIT", amount), ("Sales", "CREDIT", amount)])
    v.last_synced_at = NOW
    await books.session.flush()
    return v.voucher_id


async def priors(books: Books, amount: str = "70000", count: int = 5) -> None:
    """Identical amounts, spaced beyond anomaly.duplicate_window_days - otherwise they are
    duplicates of one another, which is the duplicate rule working correctly and not what these
    tests are about."""
    for i in range(count):
        await sale(books, START + timedelta(days=i * 5), amount)


async def a_large_one(books: Books) -> uuid.UUID:
    """Five priors of 70,000 then 4,50,000 - the SRS's own example."""
    await priors(books)
    return await sale(books, START + timedelta(days=40), "450000")


def url(books: Books, rest: str = "") -> str:
    return f"/companies/{books.company.company_id}/anomalies{rest}"


# --- AC-55: with the flag off, nothing happens at all ---------------------------------------


@pytest.mark.req("AC-55", "FR-3.1")
async def test_with_the_flag_off_no_anomaly_is_created_and_no_model_is_called(
    session: AsyncSession, books: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    await a_large_one(books)

    def must_not_be_built(*_a: Any, **_k: Any) -> Any:  # pragma: no cover
        raise AssertionError("no MCP or Claude call may be made while the flag is off")

    import anthropic
    from mcp import Client

    monkeypatch.setattr(anthropic, "AsyncAnthropic", must_not_be_built)
    monkeypatch.setattr(Client, "__init__", must_not_be_built)

    assert await anomaly_jobs.anomaly_rules(session, NOW) == 0
    assert await anomaly_jobs.anomaly_explanations(session, NOW) == 0
    assert (await session.execute(select(AnomalyFlag))).scalars().all() == []
    assert (await session.execute(select(AiToolLog))).scalars().all() == []
    assert (await session.execute(select(AnomalyScanState))).scalars().all() == []


@pytest.mark.req("AC-55")
async def test_with_the_flag_off_the_section_reports_itself_unavailable(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    r = await api.get(url(books), headers=auth_header(owner))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == anomaly_service.DISABLED
    assert body["anomalies"] == []


@pytest.mark.req("AC-55")
async def test_the_flag_off_path_never_imports_the_ai_sdks() -> None:
    """The jobs import the explainer inside the function, so a deployment that never enables the
    feature never loads anthropic or mcp. Checked in a clean interpreter."""
    import subprocess
    import sys

    probe = (
        "import sys; import app.main; app.main.create_app();"
        "assert 'anthropic' not in sys.modules, 'anthropic loaded';"
        "assert 'mcp' not in sys.modules, 'mcp loaded';"
        "print('clean')"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        cwd="backend",
        env={"PATH": __import__("os").environ["PATH"], "ENV": "test", "SCHEDULER_ENABLED": "false"},
    )
    assert done.returncode == 0, done.stderr.decode()
    assert b"clean" in done.stdout


# --- the rule job and its cursor -------------------------------------------------------------


@pytest.mark.req("AC-56")
async def test_the_job_flags_the_srs_example_and_the_api_shows_its_evidence(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, owner: User
) -> None:
    await enable(books)
    voucher_id = await a_large_one(books)
    assert await anomaly_jobs.anomaly_rules(session, NOW) == 1

    body = (await api.get(url(books), headers=auth_header(owner))).json()
    assert body["available"] is True
    (found,) = body["anomalies"]
    assert found["rule"] == AnomalyRule.UNUSUALLY_LARGE_SD
    assert found["voucher_id"] == str(voucher_id)
    assert found["party_name"] == "Customer A"
    assert Decimal(found["transaction_amount"]) == Decimal("450000")
    assert Decimal(found["historical_average"]) == Decimal("70000")
    assert Decimal(found["historical_max"]) == Decimal("70000")
    assert round(Decimal(found["deviation_percent"])) == 543
    # FR-3.7: the explanation is a separate field, and there is not one yet.
    assert found["explanation_status"] == ExplanationStatus.PENDING
    assert found["explanation_text"] is None


@pytest.mark.req("D-055")
async def test_a_held_back_voucher_stored_a_run_later_is_still_scanned(
    session: AsyncSession, books: Books
) -> None:
    """D-055 #9. A record held back by D-039 #7, or recovered by a D-041 key-list check, arrives
    later carrying a LOWER alter_id - an ALTERID cursor would skip it forever."""
    await enable(books)
    for i in range(5):
        v = await sale(books, START + timedelta(days=i * 5), "70000")
        await session.execute(
            Voucher.__table__.update().where(Voucher.voucher_id == v).values(alter_id=9000 + i)
        )
    await anomaly_jobs.anomaly_rules(session, NOW)
    assert (await session.execute(select(AnomalyFlag))).scalars().all() == []

    # Now a voucher arrives in a later run with a much LOWER alter_id than everything scanned.
    late = await sale(books, START + timedelta(days=40), "450000")
    await session.execute(
        Voucher.__table__.update().where(Voucher.voucher_id == late).values(alter_id=12)
    )
    await session.execute(
        Voucher.__table__.update()
        .where(Voucher.voucher_id == late)
        .values(last_synced_at=NOW + timedelta(minutes=30))
    )
    assert await anomaly_jobs.anomaly_rules(session, NOW + timedelta(hours=1)) == 1
    (flag,) = (await session.execute(select(AnomalyFlag))).scalars().all()
    assert flag.voucher_id == late


@pytest.mark.req("D-055")
async def test_the_first_scan_only_looks_at_recent_history(
    session: AsyncSession, books: Books
) -> None:
    """D-055 #11: switching the flag on must not flag years of history at once."""
    await enable(books)
    old = date(2025, 1, 1)
    for i in range(5):
        await sale(books, old + timedelta(days=i * 5), "70000")
    await sale(books, old + timedelta(days=40), "450000")  # would flag, but is long past
    assert await anomaly_jobs.anomaly_rules(session, NOW) == 0
    state = await session.get(AnomalyScanState, books.company.company_id)
    assert state is not None and state.last_scanned_at == NOW


async def test_a_cancelled_vouchers_flag_leaves_the_list(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, owner: User
) -> None:
    await enable(books)
    voucher_id = await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)
    assert len((await api.get(url(books), headers=auth_header(owner))).json()["anomalies"]) == 1

    voucher = await session.get(Voucher, voucher_id)
    assert voucher is not None
    voucher.status = VoucherStatus.CANCELLED
    await session.flush()
    body = (await api.get(url(books), headers=auth_header(owner))).json()
    assert body["anomalies"] == [], "it leaves the list"
    assert (await session.execute(select(AnomalyFlag))).scalars().all(), "but stays in the table"


# --- review (FR-3.8) --------------------------------------------------------------------------


@pytest.mark.req("FR-3.8")
@pytest.mark.parametrize("action", ["reviewed", "not_an_issue"])
async def test_an_owner_can_review_a_flag_and_it_is_audited(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, owner: User, action: str
) -> None:
    from app.models.config import AuditLog

    await enable(books)
    await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)
    (flag,) = (await session.execute(select(AnomalyFlag))).scalars().all()

    r = await api.post(
        url(books, f"/{flag.id}/review"), json={"action": action}, headers=auth_header(owner)
    )
    assert r.status_code == 200, r.text
    assert r.json()["reviewed"] is True
    assert r.json()["not_an_issue"] is (action == "not_an_issue")
    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "ANOMALY_REVIEWED")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entity_id == str(flag.id)
    assert rows[0].user_id == owner.user_id


async def test_an_admin_cannot_review(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    """SRS 14.1: REVIEW_ANOMALIES is the Owner's and the Accountant's, not the Admin's."""
    await enable(books)
    await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)
    (flag,) = (await session.execute(select(AnomalyFlag))).scalars().all()
    admin = await make_user(session, books.company, RoleName.ADMIN)
    r = await api.post(
        url(books, f"/{flag.id}/review"), json={"action": "reviewed"}, headers=auth_header(admin)
    )
    assert r.status_code == 403


async def test_another_companys_anomaly_cannot_be_reviewed(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, owner: User
) -> None:
    await enable(books)
    other = await make_books(session, name="Theirs")
    await enable(other)
    await a_large_one(other)
    await anomaly_jobs.anomaly_rules(session, NOW)
    (theirs,) = (await session.execute(select(AnomalyFlag))).scalars().all()
    r = await api.post(
        url(books, f"/{theirs.id}/review"), json={"action": "reviewed"}, headers=auth_header(owner)
    )
    assert r.status_code == 404


# --- the disclosure the Owner confirms (D-055 #7) --------------------------------------------


@pytest.mark.req("SEC-1.12")
async def test_the_disclosure_is_what_is_actually_sent(
    api: httpx.AsyncClient, books: Books, owner: User
) -> None:
    body = (await api.get(url(books, "/disclosure"), headers=auth_header(owner))).json()
    assert body["fields_sent"] == list(redact.FIELDS)
    # Built by the real redact(), so it cannot drift from the payload.
    assert set(body["example"]) <= set(redact.FIELDS)
    assert body["example"]["party"] == redact.PARTY
    assert "Never calculate a new number" in body["system_prompt"]
    assert any("narration" in n for n in body["never_sent"])
    assert any("names" in n for n in body["never_sent"])


async def test_an_accountant_cannot_see_the_disclosure(
    api: httpx.AsyncClient, session: AsyncSession, books: Books
) -> None:
    """It names the configured model: MANAGE_SETTINGS, like every other setting."""
    accountant = await make_user(session, books.company, RoleName.ACCOUNTANT)
    r = await api.get(url(books, "/disclosure"), headers=auth_header(accountant))
    assert r.status_code == 403


async def test_explanation_health_counts_discards_for_owners_and_admins(
    api: httpx.AsyncClient, session: AsyncSession, books: Books, owner: User
) -> None:
    """D-055 #3: so the model choice can be revisited with data."""
    await enable(books)
    await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)
    (flag,) = (await session.execute(select(AnomalyFlag))).scalars().all()
    flag.explanation_status = ExplanationStatus.UNAVAILABLE
    flag.explanation_unavailable_reason = "NUMBER_NOT_IN_EVIDENCE"
    await session.flush()

    body = (await api.get(url(books, "/explanation-health"), headers=auth_header(owner))).json()
    assert body["unavailable"] == 1
    assert body["by_reason"] == [{"reason": "NUMBER_NOT_IN_EVIDENCE", "count": 1}]

    accountant = await make_user(session, books.company, RoleName.ACCOUNTANT)
    r = await api.get(url(books, "/explanation-health"), headers=auth_header(accountant))
    assert r.status_code == 403, "VIEW_LOGS is the Owner's and the Admin's"


# --- AC-58 and the daily cap ------------------------------------------------------------------


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setenv("ANOMALY_EXPLAINER_MODEL", "claude-sonnet-5-5")
    get_settings.cache_clear()


@pytest.mark.req("AC-58")
async def test_claude_unreachable_still_shows_the_anomaly_with_its_evidence(
    api: httpx.AsyncClient,
    session: AsyncSession,
    books: Books,
    owner: User,
    configured: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-58 end to end: the rules run, the evidence is stored and shown, and the explanation is
    marked unavailable with a reason. Nothing about detection depended on the model."""
    import anthropic

    await enable(books)
    await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)

    class _Dead:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.messages = self

        async def create(self, **_k: Any) -> Any:
            raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Dead)
    assert await anomaly_jobs.anomaly_explanations(session, NOW) == 1

    (found,) = (await api.get(url(books), headers=auth_header(owner))).json()["anomalies"]
    assert Decimal(found["transaction_amount"]) == Decimal("450000")
    assert Decimal(found["historical_average"]) == Decimal("70000")
    assert found["explanation_status"] == ExplanationStatus.UNAVAILABLE
    assert found["explanation_unavailable_reason"] == "CLAUDE_UNREACHABLE"
    assert found["explanation_text"] is None


async def test_without_configuration_the_job_does_not_touch_the_flags(
    session: AsyncSession, books: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    """They stay PENDING rather than burning their retry budget on a failure that is not about
    availability, so they are explained once a key and model are set."""
    from app.core.config import get_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANOMALY_EXPLAINER_MODEL", raising=False)
    get_settings.cache_clear()
    await enable(books)
    await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)
    assert await anomaly_jobs.anomaly_explanations(session, NOW) == 0
    (flag,) = (await session.execute(select(AnomalyFlag))).scalars().all()
    assert flag.explanation_status == ExplanationStatus.PENDING
    assert flag.explanation_attempts == 0


@pytest.mark.req("D-055")
async def test_the_daily_cap_defers_the_rest_newest_first(
    session: AsyncSession, books: Books, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-055 #11: enabling the feature must not spend without limit, and what it does spend goes
    on the newest anomalies. Two parties, so each has a clean history of its own - a second large
    sale to the *same* party would not flag, because the first one is in its history by then."""
    from app.models.enums import SettingDataType

    await enable(books)
    await books.setting("anomaly.max_explanations_per_day", 1, SettingDataType.INTEGER)
    for party in ("Customer A", "Customer B"):
        for i in range(5):
            await sale(books, START + timedelta(days=i * 5), "70000", party=party)
    older = await sale(books, START + timedelta(days=40), "450000", party="Customer A")
    newer = await sale(books, START + timedelta(days=45), "450000", party="Customer B")
    assert await anomaly_jobs.anomaly_rules(session, NOW) == 2

    import anthropic

    class _Dead:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.messages = self

        async def create(self, **_k: Any) -> Any:
            raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Dead)
    assert await anomaly_jobs.anomaly_explanations(session, NOW) == 1, "the cap holds"
    tried = (
        (
            await session.execute(
                select(AnomalyFlag.voucher_id).where(AnomalyFlag.explanation_attempts > 0)
            )
        )
        .scalars()
        .all()
    )
    assert tried == [newer], "newest first, by the transaction's own date"
    assert older not in tried
    assert await anomaly_jobs.anomaly_explanations(session, NOW) == 0, "nothing left today"


@pytest.mark.req("SEC-1.14")
async def test_a_wrong_model_id_is_reported_clearly_once(
    session: AsyncSession,
    books: Books,
    configured: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-055 #3: a typo in ANOMALY_EXPLAINER_MODEL would otherwise make every explanation
    unavailable with nothing to say why."""
    import anthropic

    from app.anomaly import explainer

    monkeypatch.setattr(anomaly_jobs, "_model_checked", False)

    class _Models:
        async def retrieve(self, model: str) -> Any:
            raise anthropic.NotFoundError(message=f"model: {model}", response=None, body=None)  # type: ignore[arg-type]

    class _Client:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.models = _Models()
            self.messages = self

        async def create(self, **_k: Any) -> Any:
            raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Client)
    assert await explainer.check_model_configured() is False
    # CLAUDE.md: assert on the log record, not only the return value.
    found = assert_logged(caplog, "anomaly_explainer_model_unusable", level="error")
    assert found["model"] == "claude-sonnet-5-5"

    await enable(books)
    await a_large_one(books)
    await anomaly_jobs.anomaly_rules(session, NOW)
    await anomaly_jobs.anomaly_explanations(session, NOW)
    assert anomaly_jobs._model_checked is True, "checked once per process, not once per anomaly"
