from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from core.workflow.generator.agent.graph_ops import empty_graph
from models.workflow_assist import WorkflowAssistConversation, WorkflowAssistMessage
from services.workflow_assist.conversations import WorkflowAssistConversationService

TABLES = (WorkflowAssistConversation, WorkflowAssistMessage)

_ASK_USER_CALL = {
    "id": "ask-1",
    "name": "ask_user",
    "arguments": {"questions": [{"id": "q1", "question": "知识库怎么指定", "kind": "text"}]},
}


class FakeInvoker:
    """Queued model turns. An empty queue is a blank response that still consumes a call."""

    def __init__(self) -> None:
        self._queue: list[dict[str, Any]] = []

    def queue_text(self, text: str) -> None:
        self._queue.append({"text": text})

    def queue_tool_calls(self, calls: list[dict[str, Any]]) -> None:
        self._queue.append({"tool_calls": calls})

    def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
        if not self._queue:
            return {"text": ""}
        return self._queue.pop(0)


class FakeLimits:
    def __init__(self) -> None:
        self.max_model_calls = 8


def _app_model() -> SimpleNamespace:
    return SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow")


def _account() -> SimpleNamespace:
    return SimpleNamespace(id="account-1")


def _patch_catalogues(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.agent_initializer as init_mod

    monkeypatch.setattr(init_mod, "build_tool_catalogue", lambda *args, **kwargs: [])
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", lambda *args, **kwargs: [])
    monkeypatch.setattr(init_mod, "hydrate_agent_bindings", lambda **kwargs: kwargs["graph"])


def _seed_conversation(
    session: Session,
    *,
    graph: dict[str, Any] | None = None,
    revision: int = 0,
    base_hash: str | None = "base-hash",
    compacted_until_sequence: int | None = None,
    compacted_state: dict[str, Any] | None = None,
) -> WorkflowAssistConversation:
    service = WorkflowAssistConversationService(session)
    conversation = service.create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        draft_hash=base_hash,
    )
    conversation.candidate_base_hash = base_hash
    if graph is not None:
        conversation.candidate_graph = graph
        conversation.candidate_revision = revision
    if compacted_until_sequence is not None:
        conversation.compacted_until_sequence = compacted_until_sequence
        conversation.compacted_state = compacted_state
    session.commit()
    return conversation


def _chat_kwargs(
    session: Session,
    conversation: WorkflowAssistConversation,
    invoker: object,
    *,
    message: str = "做 RAG 测试工作流",
    current_graph: dict[str, Any] | None = None,
    draft_hash: str | None = "base-hash",
    cancellation: object | None = None,
    selected_node: str | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "conversations": WorkflowAssistConversationService(session),
        "app_model": _app_model(),
        "account": _account(),
        "message": message,
        "conversation_id": conversation.id,
        "draft_hash": draft_hash,
        "current_graph": current_graph,
        "mode": "rebuild",
        "hydrate_graph": lambda graph: graph,
        "invoker": invoker,
        "limits": FakeLimits(),
        "cancellation": cancellation,
        "selected_node": selected_node,
        "references": references,
    }


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_transport_disconnect_is_not_user_abort(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_text("正在理解需求")
    invoker.queue_tool_calls([_ASK_USER_CALL])

    chat_iter = chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker))
    name, payload = next(chat_iter)
    assert name == "message"
    assert payload["delta"] == "正在理解需求"

    chat_iter.close()

    sqlite_session.refresh(conversation)
    last_reason = conversation.last_run_termination_reason
    assert last_reason == "transport_disconnect"
    messages = (
        WorkflowAssistConversationService(sqlite_session)
        .get(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            conversation_id=conversation.id,
        )
        .messages
    )
    assert any("连接中断" in str(message.payload.get("text") or "") for message in messages)
    assert not any(message.payload.get("text") == "已停止。" for message in messages)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_explicit_abort_is_user_abort(sqlite_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_text("正在理解需求")
    invoker.queue_tool_calls([_ASK_USER_CALL])

    chat_iter = chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker))
    next(chat_iter)

    chat_mod.abort_chat_run(
        conversations=WorkflowAssistConversationService(sqlite_session),
        app_model=_app_model(),
        account=_account(),
        conversation_id=conversation.id,
    )
    rest = list(chat_iter)

    sqlite_session.refresh(conversation)
    assert conversation.last_run_termination_reason == "user_abort"
    assert any(name == "aborted" and payload["termination_reason"] == "user_abort" for name, payload in rest)
    messages = (
        WorkflowAssistConversationService(sqlite_session)
        .get(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            conversation_id=conversation.id,
        )
        .messages
    )
    assert any(message.payload.get("text") == "已停止。" for message in messages)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_ask_user_round_trip(sqlite_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)

    first_invoker = FakeInvoker()
    first_invoker.queue_tool_calls([_ASK_USER_CALL])
    first_events = list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, first_invoker)))
    assert first_events[-1][0] == "waiting_user"
    assert first_events[-1][1]["tool_call_id"] == "ask-1"

    second_invoker = FakeInvoker()
    second_invoker.queue_tool_calls([{"id": "fail-1", "name": "fail", "arguments": {"reason": "缺少知识库"}}])
    second_events = list(
        chat_mod.iter_chat_events(
            **_chat_kwargs(
                sqlite_session,
                conversation,
                second_invoker,
                message="运行时传入",
            )
        )
    )
    assert second_events[-1][0] == "failed"
    detail = WorkflowAssistConversationService(sqlite_session).get(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id=conversation.id,
    )
    ask_call = next(message for message in detail.messages if message.event_type == "tool_call")
    assert ask_call.status == "completed"
    result = next(
        message
        for message in detail.messages
        if message.event_type == "tool_result" and message.payload.get("tool_call_id") == "ask-1"
    )
    assert result.payload["content"] == "运行时传入"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_supersession_makes_old_lease_writes_fail(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    graph = {
        **empty_graph(),
        "nodes": [{"id": "keep", "data": {"type": "llm", "title": "保留"}}],
    }
    conversation = _seed_conversation(sqlite_session, graph=graph, revision=1)
    old_invoker = FakeInvoker()
    old_invoker.queue_text("旧一轮还在跑")
    old_invoker.queue_tool_calls([{"id": "del-1", "name": "delete_node", "arguments": {"node_id": "keep"}}])

    old_iter = chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, old_invoker))
    assert next(old_iter)[0] == "message"

    new_invoker = FakeInvoker()
    new_invoker.queue_tool_calls([_ASK_USER_CALL])
    new_events = list(
        chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, new_invoker, message="改需求"))
    )
    assert new_events[-1][0] == "waiting_user"

    old_rest = list(old_iter)
    assert any(
        name == "aborted" and payload["termination_reason"] == "superseded_by_new_turn" for name, payload in old_rest
    )

    sqlite_session.refresh(conversation)
    assert conversation.last_run_termination_reason in {"waiting_user", "superseded_by_new_turn"}
    nodes = (conversation.candidate_graph or {}).get("nodes") or []
    assert any(isinstance(node, dict) and node.get("id") == "keep" for node in nodes)
    messages = (
        WorkflowAssistConversationService(sqlite_session)
        .get(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            conversation_id=conversation.id,
        )
        .messages
    )
    assert any("停止上一轮" in str(message.payload.get("text") or "") for message in messages)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_invalid_finish_still_continues(sqlite_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_tool_calls([{"id": "fin-1", "name": "finish", "arguments": {"summary": "好了"}}])
    invoker.queue_tool_calls([_ASK_USER_CALL])

    events = list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))
    names = [name for name, _ in events]
    assert "done" not in names
    assert names[-1] == "waiting_user"
    finish_result = next(payload for name, payload in events if name == "tool_result" and payload["id"] == "fin-1")
    assert finish_result["ok"] is False


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_plain_text_persists_turn_complete_and_clears_active_run(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_text("已经完成")

    events = list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))
    names = [name for name, _ in events]
    assert names[-1] == "turn_complete"
    assert "done" not in names
    sqlite_session.refresh(conversation)
    assert conversation.last_run_termination_reason == "turn_complete"
    assert conversation.active_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_tool_result_may_carry_preview_graph(sqlite_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    graph = {
        **empty_graph(),
        "nodes": [{"id": "drop-me", "data": {"type": "llm", "title": "删"}}],
    }
    conversation = _seed_conversation(sqlite_session, graph=graph, revision=2)
    invoker = FakeInvoker()
    invoker.queue_tool_calls([{"id": "del-1", "name": "delete_node", "arguments": {"node_id": "drop-me"}}])
    invoker.queue_tool_calls([_ASK_USER_CALL])

    events = list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))
    result = next(payload for name, payload in events if name == "tool_result" and payload["id"] == "del-1")
    assert result["ok"] is True
    assert "graph" in result
    assert all(node.get("id") != "drop-me" for node in result["graph"]["nodes"])


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_persist_stops_when_lease_is_lost(sqlite_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    conversations = WorkflowAssistConversationService(sqlite_session)
    saved: list[bool] = []
    original = conversations.save_candidate_state

    def tracking_save(*args: Any, **kwargs: Any) -> bool:
        result = original(*args, **kwargs)
        saved.append(result)
        return result

    conversations.save_candidate_state = tracking_save  # type: ignore[method-assign]
    appended: list[bool] = []
    original_append = conversations.append_message_fenced

    def tracking_append(*args: Any, **kwargs: Any):
        row = original_append(*args, **kwargs)
        appended.append(row is not None)
        return row

    conversations.append_message_fenced = tracking_append  # type: ignore[method-assign]
    invoker = FakeInvoker()
    invoker.queue_text("先写一轮")
    invoker.queue_tool_calls([_ASK_USER_CALL])
    gen = chat_mod.iter_chat_events(
        **{
            **_chat_kwargs(sqlite_session, conversation, invoker),
            "conversations": conversations,
        }
    )
    next(gen)
    conversations.acquire_run(conversation=conversation, run_id="other-run", supersede=True)
    rest = list(gen)
    sqlite_session.refresh(conversation)
    messages = (
        WorkflowAssistConversationService(sqlite_session)
        .get(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            conversation_id=conversation.id,
        )
        .messages
    )
    assert False in saved or False in appended
    assert not any(
        message.event_type == "tool_call" and message.payload.get("name") == "ask_user" for message in messages
    )
    assert any(name == "aborted" for name, _payload in rest)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_watermark_written_only_when_level2_advanced(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    prior_state = {
        "objective": ["旧目标"],
        "user_constraints": [],
        "confirmed_facts": [],
        "decisions": [],
        "rejected_approaches": [],
        "important_resources": [],
        "pending_work": [],
        "reloadable_details": [],
    }
    conversation = _seed_conversation(
        sqlite_session,
        compacted_until_sequence=4,
        compacted_state=prior_state,
    )
    invoker = FakeInvoker()
    invoker.queue_tool_calls([_ASK_USER_CALL])
    list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))

    sqlite_session.refresh(conversation)
    assert conversation.compacted_until_sequence == 4
    assert conversation.compacted_state == prior_state


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_user_turn_does_not_change_candidate_base_hash(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session, base_hash="pinned-hash")
    invoker = FakeInvoker()
    invoker.queue_tool_calls([_ASK_USER_CALL])
    list(
        chat_mod.iter_chat_events(
            **_chat_kwargs(sqlite_session, conversation, invoker, draft_hash="different-client-hash")
        )
    )
    sqlite_session.refresh(conversation)
    assert conversation.candidate_base_hash == "pinned-hash"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_json_fallback_enters_the_same_loop(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker._queue.append(
        {
            "name": "ask_user",
            "arguments": {"questions": [{"id": "q1", "question": "知识库怎么指定", "kind": "text"}]},
        }
    )
    events = list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))
    assert events[-1][0] == "waiting_user"
    assert events[-1][1]["tool_call_id"]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_live_prompt_does_not_dump_catalogue_snapshot(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.agent_initializer as init_mod
    import services.workflow_assist.chat as chat_mod

    monkeypatch.setattr(
        init_mod,
        "build_tool_catalogue",
        lambda *args, **kwargs: [
            {
                "provider_name": "secret-provider-xyz",
                "provider_type": "builtin",
                "plugin_id": "",
                "tool_name": "secret-tool-xyz",
                "tool_label": "Secret Tool",
                "description": "must-not-appear-in-live-prompt",
            }
        ],
    )
    monkeypatch.setattr(
        init_mod,
        "build_knowledge_catalogue",
        lambda *args, **kwargs: [
            {"id": "ds-secret-catalogue-id-xyz", "name": "Secret KB", "description": "must-not-appear-in-live-prompt"}
        ],
    )
    monkeypatch.setattr(init_mod, "hydrate_agent_bindings", lambda **kwargs: kwargs["graph"])
    seen: list[str] = []

    class RecordingInvoker:
        def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
            blob = "".join(str(getattr(message, "content", None) or message) for message in (messages or []))
            seen.append(blob)
            return {"tool_calls": [_ASK_USER_CALL]}

    conversation = _seed_conversation(sqlite_session)
    list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, RecordingInvoker())))
    joined = "\n".join(seen)
    assert "catalogue" not in chat_mod.CHAT_SYSTEM_PROMPT.lower()
    assert "ds-secret-catalogue-id-xyz" not in joined
    assert "secret-provider-xyz" not in joined
    assert "must-not-appear-in-live-prompt" not in joined
    assert "Secret KB" not in joined


def test_chat_system_prompt_follows_detected_language() -> None:
    import services.workflow_assist.chat as chat_mod

    zh = chat_mod.chat_system_prompt("zh-Hans")
    en = chat_mod.chat_system_prompt("en")
    assert "Simplified Chinese" in zh
    assert "English" in en
    assert "single_choice" in zh
    assert "catalogue" not in zh.lower()
    assert "catalogue" not in chat_mod.CHAT_SYSTEM_PROMPT.lower()
    assert "referenced_nodes" in chat_mod.CHAT_SYSTEM_PROMPT
    assert "build_node must use those exact ids" in chat_mod.CHAT_SYSTEM_PROMPT
    assert "search_tools" in chat_mod.CHAT_SYSTEM_PROMPT
    assert "ask_user" in chat_mod.CHAT_SYSTEM_PROMPT


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_catalogue_pull_failure_marks_side_unavailable(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.agent_initializer as init_mod
    import services.workflow_assist.chat as chat_mod

    captured_limits: dict[str, object] = {}
    captured_ctx: dict[str, Any] = {}

    def boom_tools(tenant_id: str, *, limit: int | None = 80) -> list[object]:
        captured_limits["tool"] = limit
        raise RuntimeError("tools down")

    def boom_knowledge(tenant_id: str, *, limit: int | None = 40, raise_on_error: bool = False) -> list[object]:
        captured_limits["knowledge"] = limit
        captured_limits["raise_on_error"] = raise_on_error
        raise RuntimeError("knowledge down")

    original = init_mod.ToolContext

    def wrapping_context(**kwargs: Any) -> object:
        captured_ctx.update(vars(kwargs["env"]))
        return original(**kwargs)

    monkeypatch.setattr(init_mod, "build_tool_catalogue", boom_tools)
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", boom_knowledge)
    monkeypatch.setattr(init_mod, "hydrate_agent_bindings", lambda **kwargs: kwargs["graph"])
    monkeypatch.setattr(init_mod, "ToolContext", wrapping_context)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_tool_calls([_ASK_USER_CALL])
    list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))
    assert captured_limits["tool"] is None
    assert captured_limits["knowledge"] is None
    assert captured_ctx["tools_available"] is False
    assert captured_ctx["installed_tools"] is None
    assert captured_ctx["knowledge_available"] is False
    assert captured_ctx["installed_dataset_ids"] is None
    assert captured_ctx["builder_input"].tool_catalogue_text == ""
    assert captured_ctx["builder_input"].knowledge_catalogue_text == ""


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_builder_input_uses_run_catalogue_snapshot(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.agent_initializer as init_mod
    import services.workflow_assist.chat as chat_mod

    captured_ctx: dict[str, Any] = {}
    original = init_mod.ToolContext

    def wrapping_context(**kwargs: Any) -> object:
        captured_ctx.update(vars(kwargs["env"]))
        return original(**kwargs)

    monkeypatch.setattr(
        init_mod,
        "build_tool_catalogue",
        lambda *args, **kwargs: [
            {
                "provider_name": "google",
                "provider_type": "builtin",
                "plugin_id": "",
                "tool_name": "search",
                "tool_label": "Google Search",
                "description": "Search the web.",
            }
        ],
    )
    monkeypatch.setattr(
        init_mod,
        "build_knowledge_catalogue",
        lambda *args, **kwargs: [{"id": "ds-1", "name": "Product Docs", "description": "Documentation."}],
    )
    monkeypatch.setattr(init_mod, "hydrate_agent_bindings", lambda **kwargs: kwargs["graph"])
    monkeypatch.setattr(init_mod, "ToolContext", wrapping_context)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_tool_calls([_ASK_USER_CALL])
    list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))

    builder_input = captured_ctx["builder_input"]
    assert "google/search" in builder_input.tool_catalogue_text
    assert "Search the web." in builder_input.tool_catalogue_text
    assert "id=ds-1" in builder_input.knowledge_catalogue_text
    assert "Product Docs" in builder_input.knowledge_catalogue_text


def test_token_counter_uses_model_not_constant_one() -> None:
    import services.workflow_assist.chat as chat_mod
    from graphon.model_runtime.entities.message_entities import UserPromptMessage

    class _Model:
        def get_llm_num_tokens(self, prompt_messages: object) -> int:
            return 4242

    count = chat_mod._token_counter(_Model())  # type: ignore[arg-type]
    assert count([UserPromptMessage(content="hello")]) == 4242
    heuristic = chat_mod._token_counter(None)
    long_text = "abcd" * 80
    assert heuristic([SimpleNamespace(content=long_text)]) > 1


class _BoomInvoker:
    def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
        raise RuntimeError("provider down")


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_provider_failure_emits_error_and_clears_lease(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    events = list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, _BoomInvoker())))
    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "provider_error"
    assert "provider down" in events[-1][1]["message"]
    sqlite_session.refresh(conversation)
    assert conversation.active_run_id is None
    assert conversation.last_run_termination_reason == "provider_error"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_provider_exception_does_not_overwrite_user_abort(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    cancellation = chat_mod.ChatRunCancellation()

    class _AbortThenBoom:
        def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
            cancellation.abort("user_abort")
            raise RuntimeError("provider down")

    events = list(
        chat_mod.iter_chat_events(
            **_chat_kwargs(sqlite_session, conversation, _AbortThenBoom(), cancellation=cancellation)
        )
    )
    assert events[-1][1]["termination_reason"] == "user_abort"
    sqlite_session.refresh(conversation)
    assert conversation.last_run_termination_reason == "user_abort"
    assert conversation.active_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_abort_without_in_process_registry_is_observed(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_text("正在理解需求")
    invoker.queue_tool_calls([_ASK_USER_CALL])
    cancellation = chat_mod.ChatRunCancellation()
    chat_iter = chat_mod.iter_chat_events(
        **_chat_kwargs(sqlite_session, conversation, invoker, cancellation=cancellation)
    )
    name, payload = next(chat_iter)
    assert name == "message"
    chat_mod._ACTIVE_RUNS.clear()
    result = chat_mod.abort_chat_run(
        conversations=WorkflowAssistConversationService(sqlite_session),
        app_model=_app_model(),
        account=_account(),
        conversation_id=conversation.id,
    )
    assert result["termination_reason"] == "user_abort"
    assert cancellation.reason() == "user_abort"
    rest = list(chat_iter)
    sqlite_session.refresh(conversation)
    assert conversation.last_run_termination_reason == "user_abort"
    assert any(
        event_name == "aborted" and event_payload["termination_reason"] == "user_abort"
        for event_name, event_payload in rest
    )


_PLANNER_STATE_KEYS = (
    "planning_session",
    "pending_clarification",
    "clarification_history",
    "request_kind",
    "retry_pending_clarification",
    "last_plan_draft_hash",
)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_chat_does_not_write_planner_session_state(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod

    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_tool_calls([_ASK_USER_CALL])
    list(chat_mod.iter_chat_events(**_chat_kwargs(sqlite_session, conversation, invoker)))

    sqlite_session.refresh(conversation)
    state = conversation.state or {}
    for key in _PLANNER_STATE_KEYS:
        assert key not in state


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_fenced_loop_binds_selected_node_and_references(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.workflow_assist.chat as chat_mod
    import services.workflow_assist.chat_orchestration as orch_mod

    captured: dict[str, Any] = {}
    original = orch_mod.iter_agent_events

    def wrapping(session, *args: Any, **kwargs: Any):
        captured["session"] = session
        captured["tool_context"] = args[0] if args else kwargs.get("tool_context")
        return original(session, *args, **kwargs)

    monkeypatch.setattr(orch_mod, "iter_agent_events", wrapping)
    _patch_catalogues(monkeypatch)
    conversation = _seed_conversation(sqlite_session)
    invoker = FakeInvoker()
    invoker.queue_tool_calls([_ASK_USER_CALL])
    references = [
        {"kind": "node", "id": "n1", "label": "知识库检索"},
        {
            "kind": "tool",
            "id": "time/current_time",
            "label": "当前时间",
            "provider": "time",
            "tool_name": "current_time",
        },
        {"kind": "dataset", "id": "ds-uuid", "label": "产品文档"},
    ]
    list(
        chat_mod.iter_chat_events(
            **_chat_kwargs(
                sqlite_session,
                conversation,
                invoker,
                selected_node="n-drag",
                references=references,
            )
        )
    )

    session = captured["session"]
    assert session.selected_node == "n-drag"
    assert [item["id"] for item in session.referenced_nodes] == ["n1"]
    assert [item["id"] for item in session.referenced_tools] == ["time/current_time"]
    assert [item["id"] for item in session.referenced_datasets] == ["ds-uuid"]
    instruction = captured["tool_context"].env.builder_input.instruction
    assert "Bound user references (HARD)" in instruction
    assert "time/current_time" in instruction
    assert "ds-uuid" in instruction


def test_durable_agent_binds_run_references_and_selected_node(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.workflow_assist.agent_initializer as init_mod
    import services.workflow_assist.chat as chat_mod

    captured: dict[str, Any] = {}

    def fake_iter(session, tool_context, *args: Any, **kwargs: Any):
        captured["session"] = session
        captured["instruction"] = tool_context.env.builder_input.instruction
        return iter(())

    monkeypatch.setattr(init_mod, "iter_agent_events", fake_iter)
    monkeypatch.setattr(init_mod, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])
    references = [
        {"kind": "node", "id": "n1", "label": "知识库检索"},
        {
            "kind": "tool",
            "id": "time/current_time",
            "label": "当前时间",
            "provider": "time",
            "tool_name": "current_time",
        },
        {"kind": "dataset", "id": "ds-uuid", "label": "产品文档"},
    ]
    context = SimpleNamespace(
        app_model=SimpleNamespace(tenant_id="tenant-1", id="app-1", mode="workflow"),
        account=SimpleNamespace(id="account-1"),
        run=SimpleNamespace(
            id="run-1",
            epoch=1,
            worker_id="w1",
            model_config={"provider": "openai", "name": "gpt-4o", "mode": "chat"},
            mode="workflow",
            selected_node="node-1",
            references=references,
            input="把 知识库检索 接到当前时间",
        ),
        conversation=SimpleNamespace(
            candidate_revision=0,
            candidate_base_hash=None,
            compacted_until_sequence=None,
            compacted_state=None,
            candidate_graph={"nodes": [], "edges": []},
            state={},
        ),
        messages=(
            SimpleNamespace(
                sequence=1,
                event_type="message",
                role="user",
                status="completed",
                payload={"text": "把 知识库检索 接到当前时间", "references": references},
            ),
        ),
        should_stop=lambda: False,
    )

    list(chat_mod.run_workflow_assist_agent(context, invoker=FakeInvoker(), hydrate_graph=lambda graph: graph))

    session = captured["session"]
    assert session.selected_node == "node-1"
    assert [item["id"] for item in session.referenced_nodes] == ["n1"]
    assert [item["id"] for item in session.referenced_tools] == ["time/current_time"]
    assert [item["id"] for item in session.referenced_datasets] == ["ds-uuid"]
    assert "Bound user references (HARD)" in captured["instruction"]
    assert "time/current_time" in captured["instruction"]


def test_assist_elapsed_time_fuse_is_disabled_by_default() -> None:
    from configs.feature import WorkflowConfig
    from services.workflow_assist.chat import _limits_from_config

    assert WorkflowConfig().WORKFLOW_ASSIST_MAX_ELAPSED_TIME == 0
    assert _limits_from_config().max_elapsed_time is None
