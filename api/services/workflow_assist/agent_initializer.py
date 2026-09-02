"""Assemble runtime, catalogues, and ToolContext for one Workflow Assist loop.

HTTP SSE and durable Celery runs share this initializer so ``core`` stays free of
service imports. Catalogue snapshots are captured once per run (``limit=None``)
onto ``ToolContext``. Discovery is ``search_*``; a failed pull sets that side
``available=false`` and ``installed_*=None``. Formatted catalogues go to the
Builder via ``BuilderInput``; they are not concatenated into the live agent
prompt.

Runaway thresholds are ``WorkflowConfig`` fields on ``dify_config``
(``WORKFLOW_ASSIST_MAX_MODEL_CALLS`` and siblings), not getattr fallbacks.
Hydrate is injected into ``ToolContext`` — ``core`` must not import services.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, cast

from sqlalchemy.orm import Session

from core.app.app_config.entities import ModelConfig
from core.db.session_factory import session_factory
from core.model_manager import ModelManager
from core.workflow.generator.agent.compaction import COMPACTED_STATE_KEYS, TokenLimits, compute_input_limit
from core.workflow.generator.agent.graph_ops import empty_graph
from core.workflow.generator.agent.loop import SYSTEM_PROMPT, iter_agent_events
from core.workflow.generator.agent.session import apply_user_turn, restore_session
from core.workflow.generator.agent.tools import TOOL_SCHEMAS, ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.agent.types import (
    AgentEvent,
    AgentMessage,
    AgentSession,
    CandidateState,
    MinimalGraphDict,
)
from core.workflow.generator.knowledge_catalogue import (
    KnowledgeCatalogueEntry,
    build_knowledge_catalogue,
    format_knowledge_catalogue,
    installed_dataset_keys,
)
from core.workflow.generator.llm_response import LLMJsonClient, ModelInvoker
from core.workflow.generator.node_builder import BuilderInput
from core.workflow.generator.output_language import detect_output_language, output_language_name
from core.workflow.generator.planner_context import PlannerContextSession
from core.workflow.generator.tool_catalogue import (
    ToolCatalogueEntry,
    build_tool_catalogue,
    format_tool_catalogue,
    installed_tool_keys,
)
from core.workflow.generator.types import WorkflowGenerationMode
from graphon.model_runtime.entities.message_entities import (
    PromptMessage,
    PromptMessageTool,
    UserPromptMessage,
)
from graphon.model_runtime.entities.model_entities import ModelFeature, ModelType
from models import Account, App
from models.workflow_assist import WorkflowAssistConversation, WorkflowAssistMessage
from services.workflow_assist.effect_policy import live_run_authorized_from_session
from services.workflow_assist.hydrate import hydrate_agent_bindings
from services.workflow_assist.run_types import AGENT_RESPONSE_OUTBOX_KEY
from services.workflow_assist.sandbox import WorkflowAssistAcceptanceRunner
from services.workflow_assist.turn_references import append_hard_bound_resources, bind_session_references
from services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = (
    f"{SYSTEM_PROMPT}\n\n"
    "Available node types: start, end, answer, llm, knowledge-retrieval, code, tool, agent, "
    "and control-flow nodes (iteration, loop, if-else). Do not include node config schemas. "
    "Write assistant narration in natural language. Never echo tool-call JSON in the message body."
)


def chat_system_prompt(language: str) -> str:
    """Keep the live agent prompt language-aligned without dumping catalogues."""
    detected = language if language in {"en", "zh-Hans"} else "en"
    return (
        f"{CHAT_SYSTEM_PROMPT}\n\n"
        f"User-visible assistant prose and ask_user questions must be in {output_language_name(detected)}. "
        "Keep node ids, types, and other identifiers unchanged. "
        "When a question has a small set of answers, use single_choice or multi_choice with options "
        "instead of a mixed-language wall of text."
    )


@dataclass
class ChatRunLimits:
    """Runaway thresholds from ``dify_config`` ``WorkflowConfig`` fields."""

    max_model_calls: int
    max_tool_calls: int | None = None
    max_total_tokens: int | None = None
    max_elapsed_time: float | None = None
    token_limits: TokenLimits | None = None


class WorkflowAgentInvoker:
    """Native TOOL_CALL path or JSON ``{name, arguments}`` fallback, same loop.

    ``iter_agent_events`` consumes ``iter_chunks`` when it returns an iterator
    (native tools, ``invoke_llm(..., stream=True)``). ``invoke`` stays the
    blocking ``stream=False`` / JSON path used when ``iter_chunks`` is ``None``.
    """

    def __init__(
        self,
        *,
        model_instance: ModelInvoker,
        model_parameters: dict[str, Any],
        json_client: LLMJsonClient,
        tools: list[PromptMessageTool],
        native_tools: bool,
    ) -> None:
        self.model_instance = model_instance
        self.model_parameters = model_parameters
        self.json_client = json_client
        self.tools = tools
        self.native_tools = native_tools

    def invoke(self, messages: list[object]) -> object:
        prompt_messages = [message for message in messages if isinstance(message, PromptMessage)]
        if self.native_tools:
            result = self.model_instance.invoke_llm(
                prompt_messages=prompt_messages,
                model_parameters=self.model_parameters,
                tools=self.tools,
                stream=False,
            )
            return _turn_from_llm_result(result)
        parsed = self.json_client.invoke_json(messages=prompt_messages, stage="workflow-agent")
        return parsed

    def iter_chunks(self, messages: list[object]) -> Iterator[object] | None:
        if not self.native_tools:
            return None
        prompt_messages = [message for message in messages if isinstance(message, PromptMessage)]
        chunks = self.model_instance.invoke_llm(
            prompt_messages=prompt_messages,
            model_parameters=self.model_parameters,
            tools=self.tools,
            stream=True,
        )
        return iter(chunks)


@dataclass
class _Runtime:
    invoker: object
    json_client: LLMJsonClient
    model_instance: ModelInvoker | None
    compact: Callable[..., dict[str, object]] | None
    token_limits: TokenLimits | None


def _resolve_runtime(
    *,
    tenant_id: str,
    model_config: ModelConfig | None,
    invoker: object | None,
) -> _Runtime:
    if invoker is not None:
        json_client = LLMJsonClient(model_instance=_NullModel(), model_parameters={})
        return _Runtime(
            invoker=invoker,
            json_client=json_client,
            model_instance=None,
            compact=None,
            token_limits=None,
        )
    if model_config is None:
        raise ValueError("model_config is required when no invoker is injected")
    from configs import dify_config

    model_manager = ModelManager.for_tenant(tenant_id=tenant_id)
    model_instance = model_manager.get_model_instance(
        tenant_id=tenant_id,
        model_type=ModelType.LLM,
        provider=model_config.provider,
        model=model_config.name,
    )
    model_parameters = dict(model_config.completion_params or {})
    json_client = LLMJsonClient(model_instance=cast(ModelInvoker, model_instance), model_parameters=model_parameters)
    native = _supports_native_tools(model_instance)
    tools = [
        PromptMessageTool(name=schema["name"], description=schema["description"], parameters=schema["parameters"])
        for schema in TOOL_SCHEMAS
    ]
    agent_invoker = WorkflowAgentInvoker(
        model_instance=cast(ModelInvoker, model_instance),
        model_parameters=model_parameters,
        json_client=json_client,
        tools=tools,
        native_tools=native,
    )
    context_window, _source = PlannerContextSession._resolve_context_window(cast(ModelInvoker, model_instance))
    output_reserve = max(1024, int(context_window * 0.25))
    input_limit = compute_input_limit(context_window=context_window, output_reserve=output_reserve)
    token_limits = TokenLimits(
        input_limit=input_limit,
        compact_trigger=int(input_limit * 0.8),
        compact_target=int(input_limit * 0.7),
        compactor_input_limit=max(int(dify_config.WORKFLOW_ASSIST_COMPACTOR_INPUT_LIMIT), 1),
    )
    return _Runtime(
        invoker=agent_invoker,
        json_client=json_client,
        model_instance=cast(ModelInvoker, model_instance),
        compact=_llm_compact(json_client),
        token_limits=token_limits,
    )


def _supports_native_tools(model_instance: object) -> bool:
    try:
        schema = model_instance.get_model_schema()  # type: ignore[attr-defined]
        features = getattr(schema, "features", None) or []
        return ModelFeature.TOOL_CALL in features or ModelFeature.MULTI_TOOL_CALL in features
    except Exception:
        logger.info("Workflow assist: could not read model tool-call features", exc_info=True)
        return False


def _turn_from_llm_result(result: object) -> dict[str, Any]:
    message = getattr(result, "message", result)
    text = ""
    get_text = getattr(message, "get_text_content", None)
    if callable(get_text):
        text = get_text() or ""
    elif isinstance(getattr(message, "content", None), str):
        text = message.content
    calls: list[dict[str, Any]] = []
    for item in getattr(message, "tool_calls", None) or []:
        function = getattr(item, "function", None)
        name = getattr(function, "name", None) if function is not None else getattr(item, "name", None)
        raw_args = getattr(function, "arguments", None) if function is not None else getattr(item, "arguments", None)
        arguments: dict[str, Any] = {}
        if isinstance(raw_args, dict):
            arguments = raw_args
        elif isinstance(raw_args, str) and raw_args:
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                arguments = parsed
        call_id = getattr(item, "id", None)
        calls.append({"id": call_id or "", "name": str(name or ""), "arguments": arguments})
    payload: dict[str, Any] = {}
    if text:
        payload["text"] = text
    if calls:
        payload["tool_calls"] = calls
    return payload


def _llm_compact(json_client: LLMJsonClient) -> Callable[..., dict[str, object]]:
    empty = {key: [] for key in COMPACTED_STATE_KEYS}

    def compact(
        *,
        compacted_state: dict[str, object] | None,
        segment: list[object],
        situation_text: str,
    ) -> dict[str, object]:
        prompt = (
            "Summarize the following workflow-agent transcript into a JSON object with exactly these "
            f"list-valued keys: {', '.join(COMPACTED_STATE_KEYS)}. "
            "Do not invent tools. Preserve user constraints and confirmed facts.\n\n"
            f"previous={json.dumps(compacted_state or empty, ensure_ascii=False)}\n"
            f"segment={_segment_text(segment)}\n"
            f"situation={situation_text}"
        )
        try:
            parsed = json_client.invoke_json(
                messages=[UserPromptMessage(content=prompt)],
                stage="workflow-agent-compactor",
            )
        except Exception:
            logger.warning("Workflow assist: compactor invoke failed", exc_info=True)
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return compact


def _segment_text(segment: list[object]) -> str:
    parts: list[str] = []
    for item in segment:
        payload = getattr(item, "payload", None)
        parts.append(json.dumps(payload, ensure_ascii=False, default=str) if isinstance(payload, dict) else str(item))
    return "\n".join(parts)[:8000]


def _token_counter(model_instance: ModelInvoker | None) -> Callable[[list[object]], int]:
    def count(messages: list[object]) -> int:
        prompt_messages = [message for message in messages if isinstance(message, PromptMessage)]
        if model_instance is not None and prompt_messages:
            try:
                return max(model_instance.get_llm_num_tokens(prompt_messages), 0)
            except Exception:
                logger.warning("Workflow assist: token count failed, using length heuristic", exc_info=True)
        parts: list[str] = []
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                parts.append(content)
            else:
                parts.append(str(message))
        return max(len("".join(parts)) // 4, 1)

    return count


def _limits_from_config() -> ChatRunLimits:
    from configs import dify_config

    elapsed = int(dify_config.WORKFLOW_ASSIST_MAX_ELAPSED_TIME)
    return ChatRunLimits(
        max_model_calls=int(dify_config.WORKFLOW_ASSIST_MAX_MODEL_CALLS),
        max_tool_calls=int(dify_config.WORKFLOW_ASSIST_MAX_TOOL_CALLS),
        max_total_tokens=int(dify_config.WORKFLOW_ASSIST_MAX_TOTAL_TOKENS),
        max_elapsed_time=float(elapsed) if elapsed > 0 else None,
    )


def _catalogue_snapshot(
    tenant_id: str,
) -> tuple[
    list[ToolCatalogueEntry],
    list[KnowledgeCatalogueEntry],
    set[tuple[str, str]] | None,
    set[str] | None,
    bool,
    bool,
]:
    try:
        tool_entries = build_tool_catalogue(tenant_id, limit=None)
        installed_tools: set[tuple[str, str]] | None = installed_tool_keys(tool_entries)
        tools_available = True
    except Exception:
        logger.exception("Workflow assist: tool catalogue snapshot failed for tenant %s", tenant_id)
        tool_entries = []
        installed_tools = None
        tools_available = False
    try:
        knowledge_entries = build_knowledge_catalogue(tenant_id, limit=None, raise_on_error=True)
        installed_datasets: set[str] | None = installed_dataset_keys(knowledge_entries)
        knowledge_available = True
    except Exception:
        logger.exception("Workflow assist: knowledge catalogue snapshot failed for tenant %s", tenant_id)
        knowledge_entries = []
        installed_datasets = None
        knowledge_available = False
    return tool_entries, knowledge_entries, installed_tools, installed_datasets, tools_available, knowledge_available


def _bind_hydrate(
    session: Session,
    app_model: App,
    account: Account,
) -> Callable[[MinimalGraphDict], MinimalGraphDict]:
    def hydrate_graph(graph: MinimalGraphDict) -> MinimalGraphDict:
        draft = WorkflowService().get_draft_workflow(app_model=app_model, session=session)
        if draft is None:
            return graph
        hydrated = hydrate_agent_bindings(
            session=session,
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(account.id),
            workflow_id=str(draft.id),
            graph=dict(graph),
        )
        return cast(MinimalGraphDict, hydrated)

    return hydrate_graph


def _builder_input(
    model_config: ModelConfig | None,
    generation_mode: WorkflowGenerationMode,
    instruction: str,
    current_graph: dict[str, Any] | None,
    *,
    tool_entries: list[ToolCatalogueEntry],
    knowledge_entries: list[KnowledgeCatalogueEntry],
    tools_available: bool,
    knowledge_available: bool,
    references: list[dict[str, Any]] | None = None,
) -> BuilderInput:
    """Builder sees the same HTTP-run catalogue snapshot as search/validate.

    Unavailable sides stay empty text (skip that section) rather than dumping
    catalogues into the live agent prompt.
    """
    return BuilderInput(
        provider=model_config.provider if model_config else "openai",
        model_name=model_config.name if model_config else "gpt-4o",
        model_mode=str(model_config.mode) if model_config else "chat",
        mode=generation_mode,
        instruction=append_hard_bound_resources(instruction, references),
        ideal_output="",
        plan_nodes=[],
        plan_edges=[],
        tool_catalogue_text=format_tool_catalogue(tool_entries) if tools_available else "",
        knowledge_catalogue_text=format_knowledge_catalogue(knowledge_entries) if knowledge_available else "",
        start_inputs=[],
        current_graph=current_graph,
        output_language=detect_output_language(instruction),
    )


def _candidate_state(conversation: WorkflowAssistConversation) -> CandidateState:
    last_validation = None
    if isinstance(conversation.state, dict):
        raw_validation = conversation.state.get("last_validation")
        if isinstance(raw_validation, dict):
            last_validation = raw_validation
    state: CandidateState = {
        "revision": conversation.candidate_revision or 0,
        "base_hash": conversation.candidate_base_hash,
        "compacted_until_sequence": conversation.compacted_until_sequence,
        "compacted_state": conversation.compacted_state,
    }
    if last_validation is not None:
        state["last_validation"] = last_validation
    graph = conversation.candidate_graph
    if isinstance(graph, dict):
        state["graph"] = graph
    return state


def _generation_mode(app_model: App) -> WorkflowGenerationMode:
    mode = str(getattr(app_model, "mode", "workflow"))
    return "advanced-chat" if mode == "advanced-chat" else "workflow"


class _NullModel:
    """Stand-in so injected test invokers still construct ``LLMJsonClient``."""

    def invoke_llm(self, **kwargs: object) -> object:
        raise RuntimeError("LLM is not configured for this workflow-assist test run")

    def get_model_schema(self) -> object:
        return None

    def get_llm_num_tokens(self, prompt_messages: object) -> int:
        return max(len(str(prompt_messages)) // 4, 1)


class WorkflowAssistRunInitializationError(RuntimeError):
    """Raised when durable inputs cannot initialize the production Agent loop."""


class DurableAgentRunContext(Protocol):
    @property
    def app_model(self) -> Any: ...

    @property
    def account(self) -> Any: ...

    @property
    def run(self) -> Any: ...

    @property
    def conversation(self) -> Any: ...

    @property
    def messages(self) -> tuple[Any, ...]: ...

    @property
    def should_stop(self) -> Callable[[], bool]: ...


class _FenceCancellation:
    def __init__(self, should_stop: Callable[[], bool]) -> None:
        self._should_stop = should_stop

    def reason(self) -> str | None:
        return "worker_lost" if self._should_stop() else None


def restore_http_agent_session(
    *,
    app_model: App,
    conversation: WorkflowAssistConversation,
    detail_messages: list[WorkflowAssistMessage],
    message: str,
    draft_hash: str | None,
    current_graph: dict[str, Any] | None,
    mode: Literal["local", "rebuild"],
    selected_node: str | None,
    references: list[dict[str, Any]] | None,
) -> AgentSession:
    """Rebuild the in-memory session for one HTTP chat/stream turn."""
    generation_mode = _generation_mode(app_model)
    agent_session = restore_session(
        detail_messages,
        _candidate_state(conversation),
        generation_mode,
    )
    agent_session = apply_user_turn(agent_session, message, references)
    agent_session.edit_mode = mode
    agent_session.last_run = conversation.last_run_termination_reason
    agent_session.canvas_graph = current_graph
    agent_session.canvas_hash = draft_hash
    agent_session.selected_node = selected_node
    bind_session_references(agent_session, references)
    return agent_session


def build_http_tool_context(
    *,
    app_model: App,
    account: Account,
    message: str,
    current_graph: dict[str, Any] | None,
    model_config: ModelConfig | None,
    references: list[dict[str, Any]] | None,
    invoker: object | None,
    hydrate_graph: Callable[[MinimalGraphDict], MinimalGraphDict] | None,
    db_session: Session,
    agent_session: AgentSession,
) -> tuple[ToolContext, _Runtime]:
    """Snapshot catalogues and assemble the ToolContext for one HTTP run."""
    generation_mode = _generation_mode(app_model)
    tool_entries, knowledge_entries, installed_tools, installed_datasets, tools_available, knowledge_available = (
        _catalogue_snapshot(str(app_model.tenant_id))
    )
    runtime = _resolve_runtime(
        tenant_id=str(app_model.tenant_id),
        model_config=model_config,
        invoker=invoker,
    )
    bound_hydrate = hydrate_graph if hydrate_graph is not None else _bind_hydrate(db_session, app_model, account)
    graph = agent_session.candidate_graph if isinstance(agent_session.candidate_graph, dict) else empty_graph()
    context = ToolContext(
        env=ToolEnv(
            tenant_id=str(app_model.tenant_id),
            mode=generation_mode,
            tool_entries=tool_entries,
            knowledge_entries=knowledge_entries,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_datasets,
            knowledge_available=knowledge_available,
            tools_available=tools_available,
            builder_input=_builder_input(
                model_config,
                generation_mode,
                message,
                current_graph,
                tool_entries=tool_entries,
                knowledge_entries=knowledge_entries,
                tools_available=tools_available,
                knowledge_available=knowledge_available,
                references=references,
            ),
            llm_client=runtime.json_client,
            hydrate_graph=bound_hydrate,
            acceptance_runner=WorkflowAssistAcceptanceRunner(
                tenant_id=str(app_model.tenant_id),
                app_id=str(app_model.id),
                user_id=str(account.id),
            ),
            live_run_authorized=live_run_authorized_from_session(agent_session),
        ),
        state=ToolTurnState(
            graph=cast(MinimalGraphDict, graph),
            candidate_revision=agent_session.candidate_revision,
        ),
    )
    return context, runtime


def run_workflow_assist_agent(
    context: DurableAgentRunContext,
    *,
    invoker: object | None = None,
    hydrate_graph: Callable[[MinimalGraphDict], MinimalGraphDict] | None = None,
) -> Iterator[AgentEvent]:
    """Restore one durable session and stream the real in-memory Agent loop."""
    try:
        model_config = ModelConfig.model_validate(context.run.model_config)
        generation_mode: WorkflowGenerationMode = (
            "advanced-chat" if str(context.run.mode) == "advanced-chat" else "workflow"
        )
        session = restore_session(context.messages, _candidate_state(context.conversation), generation_mode)
        _validate_applied_input(session.messages, str(context.run.input))
        session.selected_node = getattr(context.run, "selected_node", None)
        bind_session_references(session, getattr(context.run, "references", None))
        try:
            tool_entries = build_tool_catalogue(str(context.app_model.tenant_id), limit=None)
            knowledge_entries = build_knowledge_catalogue(
                str(context.app_model.tenant_id), limit=None, raise_on_error=True
            )
        except Exception as exc:
            raise WorkflowAssistRunInitializationError("failed to initialize owner-scoped catalogues") from exc
        runtime = _resolve_runtime(
            tenant_id=str(context.app_model.tenant_id),
            model_config=model_config,
            invoker=invoker,
        )
        graph = session.candidate_graph if isinstance(session.candidate_graph, dict) else empty_graph()
        bound_hydrate = hydrate_graph or _bind_durable_hydrate(context)
        tool_context = ToolContext(
            env=ToolEnv(
                tenant_id=str(context.app_model.tenant_id),
                mode=generation_mode,
                tool_entries=tool_entries,
                knowledge_entries=knowledge_entries,
                installed_tools=installed_tool_keys(tool_entries),
                installed_dataset_ids=installed_dataset_keys(knowledge_entries),
                knowledge_available=True,
                tools_available=True,
                builder_input=_builder_input(
                    model_config,
                    generation_mode,
                    str(context.run.input),
                    dict(graph),
                    tool_entries=tool_entries,
                    knowledge_entries=knowledge_entries,
                    tools_available=True,
                    knowledge_available=True,
                    references=getattr(context.run, "references", None),
                ),
                llm_client=runtime.json_client,
                hydrate_graph=bound_hydrate,
                acceptance_runner=WorkflowAssistAcceptanceRunner(
                    tenant_id=str(context.app_model.tenant_id),
                    app_id=str(context.app_model.id),
                    user_id=str(context.account.id),
                ),
                live_run_authorized=live_run_authorized_from_session(session),
            ),
            state=ToolTurnState(
                graph=cast(MinimalGraphDict, graph),
                candidate_revision=session.candidate_revision,
            ),
        )
    except WorkflowAssistRunInitializationError:
        raise
    except Exception as exc:
        raise WorkflowAssistRunInitializationError("failed to initialize Workflow Assist Agent loop") from exc

    observed_count = len(session.messages)
    pending_messages: list[AgentMessage] = []
    pending_events = _pending_agent_response(context)
    for event_name, pending_payload in pending_events:
        yield event_name, pending_payload
    for event_name, raw_payload in iter_agent_events(
        session,
        tool_context,
        cast(Any, runtime.invoker),
        _FenceCancellation(context.should_stop),
        _limits_from_config(),
        compact=runtime.compact,
        system_text=chat_system_prompt(detect_output_language(str(context.run.input))),
        token_counter=_token_counter(runtime.model_instance),
        token_limits=runtime.token_limits,
    ):
        payload = dict(raw_payload)
        pending_messages.extend(session.messages[observed_count:])
        observed_count = len(session.messages)
        persist_now = event_name in {"message", "tool_result"} or (
            event_name == "reasoning.delta" and bool(pending_messages)
        ) or (
            event_name == "tool_call"
            and len(pending_messages) == 1
            and pending_messages[0].event_type == "tool_call"
            and pending_messages[0].status == "pending"
        )
        if persist_now:
            payload["_agent_checkpoint"] = _serialize_agent_checkpoint(session)
            if pending_messages:
                payload["_recovery_messages"] = [_serialize_agent_message(message) for message in pending_messages]
                pending_messages = []
        yield event_name, payload


def _serialize_agent_message(message: AgentMessage) -> dict[str, Any]:
    return asdict(message)


def _serialize_agent_checkpoint(session: AgentSession) -> dict[str, Any]:
    return {
        "compacted_until_sequence": session.compacted_until_sequence,
        "compacted_state": session.compacted_state,
        "last_validation": session.last_validation,
    }


def _validate_applied_input(messages: list[AgentMessage], run_input: str) -> None:
    """Ensure start_turn atomically applied this run input before enqueue."""
    if not messages:
        raise WorkflowAssistRunInitializationError("durable run has no applied input")
    for message in reversed(messages):
        if message.role == "user" and message.event_type == "message":
            if message.payload.get("text") == run_input:
                return
            break
        answered = (
            message.role == "assistant"
            and message.event_type == "tool_result"
            and message.payload.get("name") == "ask_user"
        )
        if answered:
            if message.payload.get("content") == run_input:
                return
            break
    raise WorkflowAssistRunInitializationError("durable run input does not match restored Agent history")


def _bind_durable_hydrate(context: DurableAgentRunContext) -> Callable[[MinimalGraphDict], MinimalGraphDict]:
    def hydrate(graph: MinimalGraphDict) -> MinimalGraphDict:
        with session_factory.create_session() as session:
            draft = WorkflowService().get_draft_workflow(app_model=context.app_model, session=session)
            if draft is None:
                raise WorkflowAssistRunInitializationError("workflow draft is missing")
            hydrated = hydrate_agent_bindings(
                session=session,
                tenant_id=str(context.app_model.tenant_id),
                app_id=str(context.app_model.id),
                account_id=str(context.account.id),
                workflow_id=draft.id,
                graph=dict(graph),
            )
            session.commit()
            return cast(MinimalGraphDict, hydrated)

    return hydrate


def _pending_agent_response(context: DurableAgentRunContext) -> list[tuple[str, dict[str, Any]]]:
    messages = context.messages
    pending = [
        message
        for message in messages
        if message.role == "assistant" and message.event_type == "message" and message.status == "pending"
    ]
    if not pending:
        return []
    if len(pending) != 1 or pending[0] is not messages[-1]:
        raise WorkflowAssistRunInitializationError("durable Agent response outbox is not the trailing message")
    message = pending[0]
    stored_payload = message.payload
    if not isinstance(stored_payload, dict):
        raise WorkflowAssistRunInitializationError("durable Agent response outbox payload is invalid")
    payload = dict(stored_payload)
    owner = payload.pop(AGENT_RESPONSE_OUTBOX_KEY, None)
    if not isinstance(owner, dict):
        raise WorkflowAssistRunInitializationError("durable Agent response outbox owner is invalid")
    if (
        owner.get("run_id") != context.run.id
        or owner.get("epoch") != context.run.epoch
        or owner.get("worker_id") != context.run.worker_id
    ):
        raise WorkflowAssistRunInitializationError("durable Agent response outbox owner does not match run lease")
    checkpoint = owner.get("checkpoint")
    text = payload.get("text")
    if not isinstance(text, str):
        raise WorkflowAssistRunInitializationError("durable Agent response outbox text is invalid")
    reasoning = payload.get("reasoning")
    recovery = {
        "sequence": message.sequence,
        "role": "assistant",
        "event_type": "message",
        "status": "completed",
        "payload": payload,
    }
    events: list[tuple[str, dict[str, Any]]] = []
    if isinstance(reasoning, str) and reasoning.strip():
        reasoning_event: dict[str, Any] = {
            "delta": reasoning,
            "text": reasoning,
            "_recovery_messages": [recovery],
        }
        message_id = payload.get("message_id")
        if isinstance(message_id, str) and message_id.strip():
            reasoning_event["message_id"] = message_id.strip()
        if checkpoint is not None:
            if not isinstance(checkpoint, dict):
                raise WorkflowAssistRunInitializationError("durable Agent response checkpoint is invalid")
            reasoning_event["_agent_checkpoint"] = checkpoint
            checkpoint = None
        events.append(("reasoning.delta", reasoning_event))
        recovery_for_text: list[dict[str, Any]] = []
    else:
        recovery_for_text = [recovery]
    if text.strip() or not events:
        message_event: dict[str, Any] = {
            "delta": text,
            "_recovery_messages": recovery_for_text,
        }
        if checkpoint is not None:
            if not isinstance(checkpoint, dict):
                raise WorkflowAssistRunInitializationError("durable Agent response checkpoint is invalid")
            message_event["_agent_checkpoint"] = checkpoint
        events.append(("message", message_event))
    return events
