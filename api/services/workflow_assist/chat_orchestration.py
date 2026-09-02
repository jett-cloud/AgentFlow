"""HTTP orchestration for one workflow-assist tool-loop run.

Acquire a run lease and commit it before any LLM call. Persist messages and
candidate state only while that lease still owns the conversation row. Closing
the SSE generator is ``transport_disconnect``; only ``POST .../chat/abort`` is
``user_abort``. A new chat/stream on the same conversation supersedes the old
lease so its writes fail. Mid-run provider/LLM exceptions yield SSE ``error`` with
``termination_reason=provider_error`` and clear ``active_run_id``. If an
abort reason is already recorded (``user_abort`` or other), that reason is
persisted and yielded instead of ``provider_error``.

``_ACTIVE_RUNS`` is a same-process fast path. Stop always writes
``last_run_termination_reason=user_abort`` under the current lease; workers
observe that DB flag via ``ChatRunCancellation.reason()`` so abort works
across processes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from typing import Any, Literal
from uuid import uuid4

from core.app.app_config.entities import ModelConfig
from core.workflow.generator.agent.loop import iter_agent_events
from core.workflow.generator.agent.types import AgentEvent, MinimalGraphDict
from core.workflow.generator.output_language import detect_output_language
from models import Account, App
from models.workflow_assist import WorkflowAssistConversation, WorkflowAssistMessage
from services.workflow_assist.agent_initializer import (
    _limits_from_config,
    _token_counter,
    build_http_tool_context,
    chat_system_prompt,
    restore_http_agent_session,
)
from services.workflow_assist.chat_persistence import (
    persist_run_termination,
    persist_tail,
    persist_user_turn,
)
from services.workflow_assist.conversations import ConversationRunLease, WorkflowAssistConversationService

logger = logging.getLogger(__name__)

_TERMINATION_STATUS = {
    "superseded_by_new_turn": "已根据你的新消息停止上一轮；已写入的候选图保留。",
    "user_abort": "已停止。",
    "transport_disconnect": "连接中断；候选图保留。",
}

_PROVIDER_ERROR = "provider_error"

_ACTIVE_LOCK = threading.Lock()


class ChatRunCancellation:
    """Abort signal for one chat/stream. First reason wins.

    The in-process registry is a fast path. ``reason()`` also reads
    ``last_run_termination_reason=user_abort`` for the current lease so a
    Stop issued on another worker is visible on the next loop check.
    """

    lease: ConversationRunLease | None
    persisted: bool
    _reason: str | None
    _conversations: WorkflowAssistConversationService | None

    def __init__(self) -> None:
        self.lease = None
        self.persisted = False
        self._reason = None
        self._conversations = None

    def abort(self, reason: str) -> None:
        if self._reason is None:
            self._reason = reason

    def reason(self) -> str | None:
        if self._reason is not None:
            return self._reason
        if self.lease is None or self._conversations is None:
            return None
        observed = self._conversations.termination_reason_for_lease(self.lease)
        if observed == "user_abort":
            self._reason = "user_abort"
        return self._reason


_ACTIVE_RUNS: dict[str, ChatRunCancellation] = {}


def iter_chat_events(
    *,
    conversations: WorkflowAssistConversationService,
    app_model: App,
    account: Account,
    message: str,
    conversation_id: str | None,
    draft_hash: str | None = None,
    current_graph: dict[str, Any] | None = None,
    mode: Literal["local", "rebuild"] = "local",
    model_config: ModelConfig | None = None,
    selected_node: str | None = None,
    references: list[dict[str, Any]] | None = None,
    invoker: object | None = None,
    limits: object | None = None,
    hydrate_graph: Callable[[MinimalGraphDict], MinimalGraphDict] | None = None,
    cancellation: ChatRunCancellation | None = None,
) -> Iterator[AgentEvent]:
    """Yield locked SSE ``(event, payload)`` tuples for one chat/stream request.

    Persists the incoming user turn (or pending ``ask_user`` answer), snapshots
    catalogues, runs ``iter_agent_events``, and writes each new message plus
    candidate state only while the lease holds. Generator close is
    ``transport_disconnect`` and is never rewritten as ``user_abort``.
    """
    detail = _get_or_create_conversation(
        conversations,
        app_model=app_model,
        account=account,
        conversation_id=conversation_id,
        draft_hash=draft_hash,
        title_hint=message,
    )
    conversation = detail.conversation
    conversations.pin_candidate_base_hash(conversation, draft_hash)

    run_cancellation = cancellation or ChatRunCancellation()
    run_cancellation._conversations = conversations
    previous = _register_run(conversation.id, run_cancellation)
    had_live_run = conversation.active_run_id is not None or previous is not None
    if previous is not None and previous is not run_cancellation:
        previous.abort("superseded_by_new_turn")

    lease = conversations.acquire_run(conversation=conversation, run_id=uuid4().hex, supersede=had_live_run)
    run_cancellation.lease = lease
    conversations.session.refresh(conversation)

    if had_live_run:
        conversations.persist_run_termination(
            conversation=conversation,
            lease=lease,
            reason="superseded_by_new_turn",
            status_text=_TERMINATION_STATUS["superseded_by_new_turn"],
            clear_active=False,
        )
        conversations.session.refresh(conversation)
        detail = conversations.get(
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(account.id),
            conversation_id=conversation.id,
        )
        conversation = detail.conversation

    try:
        yield from _run_fenced_loop(
            conversations=conversations,
            conversation=conversation,
            detail_messages=list(detail.messages),
            lease=lease,
            cancellation=run_cancellation,
            app_model=app_model,
            account=account,
            message=message,
            draft_hash=draft_hash,
            current_graph=current_graph,
            mode=mode,
            model_config=model_config,
            selected_node=selected_node,
            references=references,
            invoker=invoker,
            limits=limits,
            hydrate_graph=hydrate_graph,
        )
    except GeneratorExit:
        if run_cancellation.reason() is None:
            run_cancellation.abort("transport_disconnect")
        reason = run_cancellation.reason() or "transport_disconnect"
        persist_run_termination(
            conversations,
            conversation,
            run_cancellation,
            reason,
            clear_active=True,
            status_text=_TERMINATION_STATUS.get(reason),
        )
        raise
    except Exception as exc:
        logger.exception("Workflow assist: provider or loop failure conversation_id=%s", conversation.id)
        existing = run_cancellation.reason()
        if existing:
            reason = existing
            yield ("aborted", {"termination_reason": reason})
            persist_run_termination(
                conversations,
                conversation,
                run_cancellation,
                reason,
                clear_active=True,
                status_text=_TERMINATION_STATUS.get(reason),
            )
        else:
            reason = _PROVIDER_ERROR
            run_cancellation.abort(reason)
            yield (
                "error",
                {
                    "message": str(exc) or "Model provider failed",
                    "errors": [{"detail": str(exc)}],
                    "termination_reason": reason,
                },
            )
            persist_run_termination(conversations, conversation, run_cancellation, reason, clear_active=True)
    finally:
        _unregister_run(conversation.id, run_cancellation)


def abort_chat_run(
    *,
    conversations: WorkflowAssistConversationService,
    app_model: App,
    account: Account,
    conversation_id: str,
) -> dict[str, str]:
    """Explicit Stop. Independent of tearing SSE. Persists ``user_abort``.

    Writes the DB flag under the live lease even when this process has no
    ``_ACTIVE_RUNS`` entry, so the worker that owns the stream can observe it.
    """
    detail = conversations.get(
        tenant_id=str(app_model.tenant_id),
        app_id=str(app_model.id),
        account_id=str(account.id),
        conversation_id=conversation_id,
    )
    with _ACTIVE_LOCK:
        cancellation = _ACTIVE_RUNS.get(conversation_id)
    if cancellation is not None:
        cancellation.abort("user_abort")
    conversations.request_user_abort(detail.conversation)
    if cancellation is not None:
        persist_run_termination(
            conversations,
            detail.conversation,
            cancellation,
            "user_abort",
            clear_active=False,
            status_text=_TERMINATION_STATUS["user_abort"],
        )
    return {"termination_reason": "user_abort"}


def _run_fenced_loop(
    *,
    conversations: WorkflowAssistConversationService,
    conversation: WorkflowAssistConversation,
    detail_messages: list[WorkflowAssistMessage],
    lease: ConversationRunLease,
    cancellation: ChatRunCancellation,
    app_model: App,
    account: Account,
    message: str,
    draft_hash: str | None,
    current_graph: dict[str, Any] | None,
    mode: Literal["local", "rebuild"],
    model_config: ModelConfig | None,
    selected_node: str | None,
    references: list[dict[str, Any]] | None,
    invoker: object | None,
    limits: object | None,
    hydrate_graph: Callable[[MinimalGraphDict], MinimalGraphDict] | None,
) -> Iterator[AgentEvent]:
    agent_session = restore_http_agent_session(
        app_model=app_model,
        conversation=conversation,
        detail_messages=detail_messages,
        message=message,
        draft_hash=draft_hash,
        current_graph=current_graph,
        mode=mode,
        selected_node=selected_node,
        references=references,
    )
    prior_last = detail_messages[-1] if detail_messages else None

    if not persist_user_turn(conversations, conversation, lease, agent_session, prior_last):
        cancellation.abort("superseded_by_new_turn")
        yield ("aborted", {"termination_reason": "superseded_by_new_turn"})
        return

    last_persisted = agent_session.messages[-1].sequence
    watermark_at_start = agent_session.compacted_until_sequence
    context, runtime = build_http_tool_context(
        app_model=app_model,
        account=account,
        message=message,
        current_graph=current_graph,
        model_config=model_config,
        references=references,
        invoker=invoker,
        hydrate_graph=hydrate_graph,
        db_session=conversations.session,
        agent_session=agent_session,
    )
    run_limits = limits or _limits_from_config()
    token_counter = _token_counter(runtime.model_instance)
    terminal: str | None = None

    for event_name, payload in iter_agent_events(
        agent_session,
        context,
        runtime.invoker,
        cancellation,
        run_limits,
        compact=runtime.compact,
        system_text=chat_system_prompt(detect_output_language(message)),
        token_counter=token_counter,
        token_limits=runtime.token_limits,
    ):
        if not persist_tail(
            conversations,
            conversation,
            lease,
            agent_session,
            last_persisted=last_persisted,
            watermark_at_start=watermark_at_start,
        ):
            if cancellation.reason() is None:
                cancellation.abort("superseded_by_new_turn")
            reason = cancellation.reason() or "superseded_by_new_turn"
            yield ("aborted", {"termination_reason": reason})
            persist_run_termination(
                conversations,
                conversation,
                cancellation,
                reason,
                clear_active=True,
                status_text=_TERMINATION_STATUS.get(reason),
            )
            return
        last_persisted = agent_session.messages[-1].sequence if agent_session.messages else last_persisted
        if event_name in {"done", "failed", "waiting_user", "turn_complete"}:
            terminal = event_name
        elif event_name == "aborted":
            terminal = str(payload.get("termination_reason") or "user_abort")
        elif event_name == "error":
            terminal = str(payload.get("termination_reason") or "error")
        yield (event_name, payload)

    if terminal is not None:
        persist_run_termination(
            conversations,
            conversation,
            cancellation,
            terminal,
            clear_active=True,
            status_text=_TERMINATION_STATUS.get(terminal),
        )


def _get_or_create_conversation(
    conversations: WorkflowAssistConversationService,
    *,
    app_model: App,
    account: Account,
    conversation_id: str | None,
    draft_hash: str | None,
    title_hint: str,
) -> Any:
    if conversation_id:
        return conversations.get(
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(account.id),
            conversation_id=conversation_id,
        )
    title = " ".join(title_hint.split())[:255] or "New workflow chat"
    conversation = conversations.create(
        tenant_id=str(app_model.tenant_id),
        app_id=str(app_model.id),
        account_id=str(account.id),
        title=title,
        draft_hash=draft_hash,
    )
    conversations.session.commit()
    return conversations.get(
        tenant_id=str(app_model.tenant_id),
        app_id=str(app_model.id),
        account_id=str(account.id),
        conversation_id=conversation.id,
    )


def _register_run(conversation_id: str, cancellation: ChatRunCancellation) -> ChatRunCancellation | None:
    with _ACTIVE_LOCK:
        previous = _ACTIVE_RUNS.get(conversation_id)
        _ACTIVE_RUNS[conversation_id] = cancellation
        return previous


def _unregister_run(conversation_id: str, cancellation: ChatRunCancellation) -> None:
    with _ACTIVE_LOCK:
        if _ACTIVE_RUNS.get(conversation_id) is cancellation:
            del _ACTIVE_RUNS[conversation_id]
