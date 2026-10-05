"""Asks Claude to put one anomaly's stored evidence into a sentence (FR-3.6, SEC-1.12, SEC-1.14).

It computes nothing, and nothing it does can affect a figure or block detection: every failure
path ends in `UNAVAILABLE` with a reason, and the anomaly keeps its evidence (AC-58, NFR-REL-1).

Three details of the current models shape this code, verified against the live documentation
rather than assumed:

* **Forced tool use returns 400.** `tool_choice` is `auto`, and the system prompt names the tool
  instead. `{"type": "tool"}` - the obvious thing to write - would fail every call.
* **Thinking cannot be disabled**, so `thinking` is omitted (adaptive) and depth is controlled
  with `output_config.effort`, which this task needs little of.
* **Assistant prefill returns 400**, so the answer is not primed.

The model and the API key come only from configuration (SEC-1.14); a test scans `app/` to prove
no model name is written in code.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic
from mcp import Client, StdioServerParameters
from sqlalchemy.ext.asyncio import AsyncSession

from app.anomaly import mcp_server, numbers
from app.anomaly.prompt import SYSTEM_PROMPT
from app.core.config import get_settings
from app.models.config import AiToolLog, AnomalyFlag
from app.models.enums import ExplanationStatus, ExplanationUnavailableReason, ToolCallStatus
from tally_contract.log import get_logger

log = get_logger(__name__)

MAX_TOKENS = 2048
EFFORT = "low"
MAX_ROUNDS = 3  # one tool call is expected; this only stops a loop
TIMEOUT_SECONDS = 20.0


Reason = ExplanationUnavailableReason
McpFactory = Callable[[uuid.UUID], AbstractAsyncContextManager[Client]]
ClientFactory = Callable[[], anthropic.AsyncAnthropic]


@dataclass(frozen=True)
class Outcome:
    status: ExplanationStatus
    reason: Reason | None = None
    text: str | None = None


def _stdio(company_id: uuid.UUID) -> AbstractAsyncContextManager[Client]:
    """The production MCP transport: a subprocess with its credentials in the environment and
    the company fixed at spawn (D-055 #5). Tests pass an in-process server instead."""
    import os
    import sys

    settings = get_settings()
    return Client(
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.anomaly.mcp_server"],
            env={
                "PATH": os.environ.get("PATH", ""),
                mcp_server.COMPANY_ENV: str(company_id),
                mcp_server.DSN_ENV: settings.anomaly_readonly_database_url or "",
            },
        ),
        read_timeout_seconds=TIMEOUT_SECONDS,
    )


def _anthropic() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    key = settings.anthropic_api_key
    return anthropic.AsyncAnthropic(
        api_key=None if key is None else key.get_secret_value(),
        timeout=TIMEOUT_SECONDS,
        # Explicit, so the 20-second budget is not silently multiplied by the SDK's default of 2.
        max_retries=1,
    )


async def _log_tool_call(
    session: AsyncSession,
    company_id: uuid.UUID,
    arguments: dict[str, Any],
    status: ToolCallStatus,
    summary: str,
) -> None:
    """FR-3.9. Written by the explainer, not the MCP server: the server's role has no INSERT
    anywhere (D-055 #5)."""
    session.add(
        AiToolLog(
            company_id=company_id,
            tool_name=mcp_server.TOOL,
            parameters=arguments,
            result_summary=summary[:500],
            status=status.value,
        )
    )
    await session.flush()


def _tool_definition(tool: Any) -> dict[str, Any]:
    """The MCP tool, bridged to the Messages API as the one tool on offer."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.input_schema,
        # Keeps the arguments schema-valid without forcing the call, which 400s.
        "strict": True,
    }


def _text_of(message: Any) -> str:
    return "\n".join(b.text for b in message.content if getattr(b, "type", None) == "text").strip()


async def explain(
    session: AsyncSession,
    flag: AnomalyFlag,
    *,
    now: datetime,
    substitutions: dict[str, str] | None = None,
    make_mcp: McpFactory | None = None,
    make_client: ClientFactory | None = None,
) -> Outcome:
    """One explanation attempt. Records the attempt on the flag whatever happens, so the retry
    job is bounded and the daily cap can count (D-055 #11)."""
    settings = get_settings()
    flag.explanation_attempts += 1
    flag.explanation_last_attempt_at = now
    if settings.anthropic_api_key is None or not settings.anomaly_explainer_model:
        return _apply(flag, Outcome(ExplanationStatus.UNAVAILABLE, Reason.NOT_CONFIGURED))

    try:
        outcome = await _attempt(
            session,
            flag,
            model=settings.anomaly_explainer_model,
            make_mcp=make_mcp or _stdio,
            make_client=make_client or _anthropic,
            substitutions=substitutions or {},
        )
    except Exception as exc:  # the API, the MCP subprocess, the database - anything
        reason = _classify(exc)
        log.warning(
            "anomaly_explanation_failed", anomaly_id=flag.id, reason=reason.value, error=repr(exc)
        )
        outcome = Outcome(ExplanationStatus.UNAVAILABLE, reason)
    return _apply(flag, outcome)


def _leaves(exc: BaseException) -> list[BaseException]:
    """The real exceptions inside an ExceptionGroup.

    The MCP client runs on an anyio task group, which wraps whatever is raised inside its
    `async with` - so `except anthropic.APITimeoutError` never matches, and without this every
    failure would be reported as CLAUDE_UNREACHABLE, losing the distinction the owner asked to
    be able to count (D-055 #12).
    """
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


def _classify(exc: BaseException) -> Reason:
    leaves = _leaves(exc)
    if any(isinstance(e, (anthropic.APITimeoutError, TimeoutError)) for e in leaves):
        return Reason.TIMEOUT
    return Reason.CLAUDE_UNREACHABLE


def _apply(flag: AnomalyFlag, outcome: Outcome) -> Outcome:
    flag.explanation_status = outcome.status.value
    flag.explanation_text = outcome.text
    flag.explanation_unavailable_reason = None if outcome.reason is None else outcome.reason.value
    return outcome


async def _attempt(
    session: AsyncSession,
    flag: AnomalyFlag,
    *,
    model: str,
    make_mcp: McpFactory,
    make_client: ClientFactory,
    substitutions: dict[str, str],
) -> Outcome:
    async with make_mcp(flag.company_id) as mcp:
        tools = [_tool_definition(t) for t in (await mcp.list_tools()).tools]
        client = make_client()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"Explain anomaly {flag.id}."}
        ]
        evidence: dict[str, Any] = {}
        for _ in range(MAX_ROUNDS):
            # The SDK types `messages`/`tools` as its own TypedDicts; these are built from the
            # MCP tool list and the loop's own history, so the shapes are checked by the tests.
            message = await client.messages.create(  # type: ignore[call-overload]
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                # Forced tool use returns 400 on the current models; the prompt names the tool.
                tool_choice={"type": "auto"},
                output_config={"effort": EFFORT},
            )
            if message.stop_reason == "refusal":
                return Outcome(ExplanationStatus.UNAVAILABLE, Reason.REFUSED)
            if message.stop_reason != "tool_use":
                return _checked(_text_of(message), evidence, substitutions, flag.id)
            messages.append({"role": "assistant", "content": message.content})
            results = []
            for block in message.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                arguments = dict(block.input) if isinstance(block.input, dict) else {}
                result = await mcp.call_tool(block.name, arguments)
                failed = result.is_error is True
                if not failed and result.structured_content:
                    evidence |= result.structured_content
                await _log_tool_call(
                    session,
                    flag.company_id,
                    arguments,
                    ToolCallStatus.FAILED if failed else ToolCallStatus.SUCCESS,
                    str(result.content) if failed else "evidence returned",
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result.content),
                        "is_error": failed,
                    }
                )
            messages.append({"role": "user", "content": results})
    log.warning("anomaly_explanation_no_answer", anomaly_id=flag.id)
    return Outcome(ExplanationStatus.UNAVAILABLE, Reason.CLAUDE_UNREACHABLE)


def _checked(
    text: str, evidence: dict[str, Any], substitutions: dict[str, str], anomaly_id: int
) -> Outcome:
    """FR-3.6, then the placeholders are replaced with the real names, locally."""
    if not text:
        return Outcome(ExplanationStatus.UNAVAILABLE, Reason.CLAUDE_UNREACHABLE)
    made_up = numbers.invented(text, evidence)
    if made_up:
        log.warning(
            "anomaly_explanation_discarded",
            anomaly_id=anomaly_id,
            invented=made_up,
            explanation=text,
        )
        return Outcome(ExplanationStatus.UNAVAILABLE, Reason.NUMBER_NOT_IN_EVIDENCE)
    for placeholder, real in substitutions.items():
        text = text.replace(placeholder, real)
    return Outcome(ExplanationStatus.AVAILABLE, text=text)


async def check_model_configured() -> bool:
    """D-055 #3: a wrong model id would otherwise make every explanation unavailable with
    nothing to show why. Called once when the scheduler starts, if any company has the flag on."""
    settings = get_settings()
    if settings.anthropic_api_key is None or not settings.anomaly_explainer_model:
        log.info("anomaly_explainer_not_configured")
        return False
    try:
        await _anthropic().models.retrieve(settings.anomaly_explainer_model)
    except Exception as exc:
        log.error(
            "anomaly_explainer_model_unusable",
            model=settings.anomaly_explainer_model,
            error=str(exc),
        )
        return False
    return True
