from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable, Generator
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Any, Protocol

import yaml

from core.model_manager import ModelManager
from graphon.model_runtime.entities.message_entities import (
    AssistantPromptMessage,
    PromptMessageTool,
    SystemPromptMessage,
    ToolPromptMessage,
    UserPromptMessage,
)
from services.tool_plugin_generator.agent_tools import AgentWorkspace, execute_tool, tool_schemas, tool_specs
from services.tool_plugin_generator.llm_fill import (
    TenantLLMFillClient,
    resolve_tenant_llm_instance,
)
from services.tool_plugin_generator.model_capabilities import from_model_schema
from services.tool_plugin_generator.prompts import build_agent_system_prompt, infer_agent_mode
from services.tool_plugin_generator.scaffold import list_tool_names
from services.tool_plugin_generator.validator import ToolPluginValidationError, validate_plugin_files

MAX_AGENT_ITERATIONS = 16

_DEEPSEEK_REASONING_BLOCK = re.compile(
    r"<think>\s*<!--dify-deepseek-reasoning-->.*?</think>",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class AgentTurnLimits:
    """Safety budgets for one draft-only Agent turn."""

    max_iterations: int = MAX_AGENT_ITERATIONS
    max_tool_calls: int = 48
    max_wall_time_seconds: float = 300.0
    max_file_bytes: int = 2_000_000
    max_single_file_bytes: int = 512_000
    max_repeated_tool_calls: int = 3
    max_consecutive_validation_failures: int = 3


class AgentBudgetExceededError(RuntimeError):
    """Raised when a turn exceeds an explicit safety budget."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Agent budget exceeded: {reason}")
        self.reason = reason


@dataclass
class AgentToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AgentLLMStep:
    content: str = ""
    tool_calls: list[AgentToolCall] = field(default_factory=list)


class AgentCheckpointError(RuntimeError):
    """Raised when a draft checkpoint cannot be persisted safely."""


class AgentLLMClient(Protocol):
    def next_step(self, *, messages: list[Any], tools: list[PromptMessageTool]) -> AgentLLMStep: ...


class TenantAgentLLMClient:
    """Tenant LLM adapter for models with native Function Calling support."""

    def __init__(
        self,
        *,
        tenant_id: str,
        model_manager: ModelManager,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.provider = provider
        self.model = model
        self.model_manager = model_manager

    def _model_instance(self):
        return resolve_tenant_llm_instance(
            tenant_id=self.tenant_id,
            model_manager=self.model_manager,
            provider=self.provider,
            model=self.model,
        )

    def capabilities(self):
        """Return the normalized capabilities of the selected workspace model."""
        return from_model_schema(self._model_instance().get_model_schema())

    def validate_model_support(self) -> None:
        """Reject implicit or non-Function-Calling models before an agent turn starts."""
        if not self.provider or not self.model:
            raise ValueError("Tool plugin Agent requires an explicitly selected Function Calling model")
        capabilities = self.capabilities()
        if not capabilities.tool_call and not capabilities.multi_tool_call:
            raise ValueError("Selected model does not support Function Calling")

    def next_step(self, *, messages: list[Any], tools: list[PromptMessageTool]) -> AgentLLMStep:
        response = self._model_instance().invoke_llm(
            prompt_messages=messages,
            model_parameters={"temperature": 0.2},
            tools=tools,
            stream=False,
        )
        message = response.message
        content = ""
        if message is not None:
            content = _DEEPSEEK_REASONING_BLOCK.sub("", message.get_text_content() or "")
        tool_calls: list[AgentToolCall] = []
        native_calls = getattr(message, "tool_calls", None) or []
        for call in native_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(
                AgentToolCall(
                    id=str(call.id or uuid.uuid4()),
                    name=str(call.function.name),
                    arguments=arguments,
                )
            )
        return AgentLLMStep(content=content, tool_calls=tool_calls)


@dataclass
class AgentTurnResult:
    messages: list[dict[str, Any]]
    files: dict[str, str]
    preview_tool: dict[str, Any] | None
    plugin_unique_identifier: str | None
    installation_id: str | None
    task: Any | None
    dirty_installed: bool
    validation_errors: list[str]
    cancelled: bool = False


def _files_payload(files: dict[str, str]) -> list[dict[str, str]]:
    return [{"path": path, "content": content} for path, content in files.items()]


def _should_stop(is_cancelled: Callable[[], bool] | None) -> bool:
    if is_cancelled is None:
        return False
    try:
        return bool(is_cancelled())
    except Exception:
        return False


def _shorten(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _event(*, turn_id: str, event: str, **payload: Any) -> dict[str, Any]:
    return {
        "event": event,
        "turn_id": turn_id,
        "event_id": uuid.uuid4().hex,
        **payload,
    }


def compress_tool_arguments(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = dict(arguments or {})
    if name == "write_file":
        content = str(args.get("content") or "")
        return {
            "path": args.get("path"),
            "content_chars": len(content),
            "content_preview": _shorten(content, 200),
        }
    if name == "read_file":
        return {"path": args.get("path")}
    if name in {"bootstrap_scaffold", "add_tool"}:
        compressed: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 400:
                compressed[key] = _shorten(value, 400)
            else:
                compressed[key] = value
        return compressed
    return args


def compress_tool_result(name: str, result_text: str) -> str:
    if name == "read_file":
        try:
            payload = json.loads(result_text)
        except json.JSONDecodeError:
            return _shorten(result_text, 600)
        if isinstance(payload, dict):
            content = str(payload.get("content") or "")
            return json.dumps(
                {
                    "ok": payload.get("ok"),
                    "path": payload.get("path"),
                    "content_chars": len(content),
                    "content_preview": _shorten(content, 600),
                },
                ensure_ascii=False,
            )
    return _shorten(result_text, 800)


def _assistant_tool_message(
    content: str,
    tool_calls: list[dict[str, Any]],
) -> AssistantPromptMessage:
    return AssistantPromptMessage(
        content=content or "",
        tool_calls=[
            AssistantPromptMessage.ToolCall(
                id=str(item.get("id") or uuid.uuid4()),
                type="function",
                function=AssistantPromptMessage.ToolCall.ToolCallFunction(
                    name=str(item.get("name") or item.get("tool") or "unknown"),
                    arguments=json.dumps(item.get("arguments") or {}, ensure_ascii=False),
                ),
            )
            for item in tool_calls
            if isinstance(item, dict) and (item.get("name") or item.get("tool"))
        ],
    )


def hydrate_history_messages(history: list[dict[str, Any]] | None) -> list[Any]:
    """Rebuild FC-compatible prompt messages from persisted chat history."""
    messages: list[Any] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "user":
            messages.append(UserPromptMessage(content=content))
            continue
        if role != "assistant":
            continue
        raw_calls = item.get("tool_calls") or []
        if not isinstance(raw_calls, list) or not raw_calls:
            if content:
                messages.append(AssistantPromptMessage(content=content))
            continue
        normalized: list[dict[str, Any]] = []
        for call in raw_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or call.get("tool") or "")
            if not name:
                continue
            call_id = str(call.get("id") or uuid.uuid4())
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            normalized.append(
                {
                    "id": call_id,
                    "name": name,
                    "arguments": compress_tool_arguments(name, arguments),
                    "result": str(call.get("result") or call.get("summary") or ""),
                }
            )
        if not normalized:
            if content:
                messages.append(AssistantPromptMessage(content=content))
            continue
        messages.append(_assistant_tool_message(content, normalized))
        for call in normalized:
            messages.append(
                ToolPromptMessage(
                    content=call["result"] or json.dumps({"ok": True, "note": "no result stored"}),
                    tool_call_id=call["id"],
                )
            )
    return messages


def _provider_requires_credentials(files: dict[str, str]) -> bool:
    for path, content in files.items():
        if not (path.startswith("provider/") and path.endswith((".yaml", ".yml"))):
            continue
        try:
            doc = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and doc.get("credentials_for_provider"):
            return True
    return False


def _workspace_file_bytes(files: dict[str, str]) -> int:
    return sum(len(content.encode("utf-8")) for content in files.values())


def _check_turn_budget(*, started_at: float, clock: Callable[[], float], limits: AgentTurnLimits) -> None:
    if clock() - started_at > limits.max_wall_time_seconds:
        raise AgentBudgetExceededError("max_wall_time_seconds")


def _check_file_budget(files: dict[str, str], limits: AgentTurnLimits) -> None:
    total_bytes = _workspace_file_bytes(files)
    if total_bytes > limits.max_file_bytes:
        raise AgentBudgetExceededError("max_file_bytes")
    if any(len(content.encode("utf-8")) > limits.max_single_file_bytes for content in files.values()):
        raise AgentBudgetExceededError("max_single_file_bytes")


def _build_workspace_state(
    *,
    workspace: AgentWorkspace,
    mode: str,
    iterations_left: int,
    last_validate: str,
    last_test: str,
    plugin_identity_locked: bool,
    has_published_version: bool,
) -> dict[str, Any]:
    tools = list_tool_names(workspace.files)
    return {
        "mode": mode,
        "author": workspace.author,
        "plugin_name": workspace.plugin_name,
        "plugin_identity_locked": plugin_identity_locked,
        "active_tool_name": workspace.tool_name,
        "files_empty": not bool(workspace.files),
        "file_count": len(workspace.files),
        "existing_tools": tools,
        "tool_count": len(tools),
        "paths": sorted(workspace.files.keys()),
        "has_published_version": has_published_version,
        "credentials_required": _provider_requires_credentials(workspace.files),
        "last_validate": last_validate or "n/a",
        "last_test": last_test or "n/a",
        "iterations_left": iterations_left,
    }


def iter_agent_turn(
    *,
    message: str,
    files: dict[str, str],
    author: str,
    plugin_name: str,
    tool_name: str,
    tenant_id: str,
    user_id: str,
    llm_client: AgentLLMClient,
    history: list[dict[str, Any]] | None = None,
    has_published_version: bool = False,
    bootstrap_llm: Any | None = None,
    max_iterations: int = MAX_AGENT_ITERATIONS,
    limits: AgentTurnLimits | None = None,
    clock: Callable[[], float] = time.monotonic,
    is_cancelled: Callable[[], bool] | None = None,
    intent: str | None = None,
    plugin_identity_locked: bool | None = None,
    on_checkpoint: Callable[[dict[str, Any]], int | None] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Yield draft-only agent events for SSE streaming without installing plugins.

    Limits are checked before model/tool work and after file mutations. A
    synchronous tool cannot be pre-empted mid-call, so its timeout is enforced
    as soon as the handler returns and the outer wall-time budget remains the
    hard request boundary.
    """
    turn_limits = limits or AgentTurnLimits(max_iterations=max_iterations)
    effective_iterations = min(max_iterations, turn_limits.max_iterations)
    started_at = clock()
    _check_file_budget(files, turn_limits)
    workspace = AgentWorkspace(
        author=author,
        plugin_name=plugin_name,
        tool_name=tool_name,
        tenant_id=tenant_id,
        user_id=user_id,
        files=dict(files),
        bootstrap_llm=bootstrap_llm,
    )
    initial_files = workspace.snapshot()
    last_validate = "n/a"
    last_test = "n/a"
    locked = bool(plugin_identity_locked) if plugin_identity_locked is not None else bool(workspace.files)
    mode = infer_agent_mode(files_empty=not bool(workspace.files), intent=intent, user_message=message)

    transcript: list[dict[str, Any]] = []
    state = _build_workspace_state(
        workspace=workspace,
        mode=mode,
        iterations_left=effective_iterations,
        last_validate=last_validate,
        last_test=last_test,
        plugin_identity_locked=locked,
        has_published_version=has_published_version,
    )
    prompt_messages: list[Any] = [SystemPromptMessage(content=build_agent_system_prompt(state))]
    prompt_messages.extend(hydrate_history_messages(history))
    prompt_messages.append(UserPromptMessage(content=message))
    transcript.append({"role": "user", "content": message})
    turn_id = uuid.uuid4().hex

    tools = [
        PromptMessageTool(name=schema["name"], description=schema["description"], parameters=schema["parameters"])
        for schema in tool_schemas()
    ]
    specs_by_name = {spec.name: spec for spec in tool_specs()}

    yield _event(turn_id=turn_id, event="status", phase="thinking")

    final_assistant_text = ""
    cancelled = False
    tool_call_count = 0
    repeated_calls: dict[str, int] = {}
    consecutive_validation_failures = 0
    for iteration_index in range(effective_iterations):
        _check_turn_budget(started_at=started_at, clock=clock, limits=turn_limits)
        if _should_stop(is_cancelled):
            cancelled = True
            break

        state = _build_workspace_state(
            workspace=workspace,
            mode=mode,
            iterations_left=effective_iterations - iteration_index,
            last_validate=last_validate,
            last_test=last_test,
            plugin_identity_locked=locked,
            has_published_version=has_published_version,
        )
        prompt_messages[0] = SystemPromptMessage(content=build_agent_system_prompt(state))

        yield _event(turn_id=turn_id, event="status", phase="thinking")
        step = llm_client.next_step(messages=prompt_messages, tools=tools)
        if step.content:
            final_assistant_text = step.content
            yield _event(turn_id=turn_id, event="assistant", content=step.content)

        if not step.tool_calls:
            if step.content:
                transcript.append({"role": "assistant", "content": step.content})
            break

        assistant_message = _assistant_tool_message(
            step.content or "",
            [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in step.tool_calls
            ],
        )
        prompt_messages.append(assistant_message)
        tool_summaries: list[dict[str, Any]] = []
        for call in step.tool_calls:
            if _should_stop(is_cancelled):
                cancelled = True
                break
            _check_turn_budget(started_at=started_at, clock=clock, limits=turn_limits)
            tool_call_count += 1
            if tool_call_count > turn_limits.max_tool_calls:
                raise AgentBudgetExceededError("max_tool_calls")
            fingerprint = f"{call.name}:{json.dumps(call.arguments, sort_keys=True, ensure_ascii=False, default=str)}"
            repeated_calls[fingerprint] = repeated_calls.get(fingerprint, 0) + 1
            if repeated_calls[fingerprint] > turn_limits.max_repeated_tool_calls:
                raise AgentBudgetExceededError("repeated_tool_call")
            yield _event(
                turn_id=turn_id,
                event="tool_call",
                call_id=call.id,
                name=call.name,
                arguments=call.arguments,
            )
            yield _event(turn_id=turn_id, event="status", phase="tool", tool=call.name)
            before = workspace.snapshot()
            spec = specs_by_name.get(call.name)
            tool_started_at = clock()
            if call.name == "bootstrap_scaffold":
                thinking_queue: Queue[str] = Queue(maxsize=256)
                result_holder: dict[str, Any] = {}
                accept_thinking = Event()
                accept_thinking.set()

                def emit_thinking(
                    delta: str,
                    event_queue: Queue[str] = thinking_queue,
                    accepting: Event = accept_thinking,
                ) -> None:
                    if not accepting.is_set():
                        return
                    try:
                        event_queue.put_nowait(delta)
                    except Full:
                        pass

                bootstrap_workspace = replace(
                    workspace,
                    files=before,
                    llm_event_callback=emit_thinking,
                )

                def run_bootstrap(
                    holder: dict[str, Any] = result_holder,
                    tool_call: AgentToolCall = call,
                    current_workspace: AgentWorkspace = bootstrap_workspace,
                ) -> None:
                    try:
                        holder["result"] = execute_tool(current_workspace, tool_call.name, tool_call.arguments)
                    except Exception as exc:
                        holder["error"] = exc
                    finally:
                        current_workspace.llm_event_callback = None

                bootstrap_thread = Thread(target=copy_context().run, args=(run_bootstrap,), daemon=True)
                bootstrap_thread.start()
                cancelled_during_bootstrap = False
                try:
                    while bootstrap_thread.is_alive() or not thinking_queue.empty():
                        if _should_stop(is_cancelled):
                            cancelled = True
                            cancelled_during_bootstrap = True
                            break
                        try:
                            delta = thinking_queue.get(timeout=0.05)
                        except Empty:
                            continue
                        if delta:
                            yield _event(
                                turn_id=turn_id,
                                event="thinking",
                                call_id=call.id,
                                delta=delta,
                                done=False,
                            )
                finally:
                    accept_thinking.clear()
                if cancelled_during_bootstrap:
                    yield _event(
                        turn_id=turn_id,
                        event="thinking",
                        call_id=call.id,
                        delta="",
                        done=True,
                    )
                    break
                bootstrap_thread.join()
                if "error" in result_holder:
                    raise result_holder["error"]
                result_text = str(result_holder.get("result") or "")
                workspace.files = bootstrap_workspace.snapshot()
                yield _event(
                    turn_id=turn_id,
                    event="thinking",
                    call_id=call.id,
                    delta="",
                    done=True,
                )
            else:
                result_text = execute_tool(workspace, call.name, call.arguments)
            if clock() - tool_started_at > (spec.timeout_seconds if spec is not None else 60):
                workspace.files = before
                raise AgentBudgetExceededError("tool_timeout")
            _check_turn_budget(started_at=started_at, clock=clock, limits=turn_limits)
            try:
                _check_file_budget(workspace.files, turn_limits)
            except AgentBudgetExceededError:
                workspace.files = before
                raise
            prompt_messages.append(ToolPromptMessage(content=result_text, tool_call_id=call.id))
            summary = compress_tool_result(call.name, result_text)
            tool_summaries.append(
                {
                    "id": call.id,
                    "name": call.name,
                    "tool": call.name,
                    "arguments": compress_tool_arguments(call.name, call.arguments),
                    "result": summary,
                }
            )
            ok = True
            parsed: dict[str, Any] | None = None
            try:
                loaded = json.loads(result_text)
                if isinstance(loaded, dict):
                    parsed = loaded
                    if parsed.get("ok") is False:
                        ok = False
                if call.name == "validate" and parsed is not None:
                    last_validate = _shorten(json.dumps(parsed, ensure_ascii=False), 500)
            except json.JSONDecodeError:
                ok = True
            changed = workspace.files != before and spec is not None and spec.mutates_files
            checkpoint_messages = [
                *transcript,
                {
                    "role": "assistant",
                    "content": step.content or "",
                    "tool_calls": list(tool_summaries),
                },
            ]
            checkpoint_revision: int | None = None
            if changed and on_checkpoint is not None:
                checkpoint = {
                    "turn_id": turn_id,
                    "call_id": call.id,
                    "files": workspace.snapshot(),
                    "messages": checkpoint_messages,
                    "preview_tool": workspace.preview_tool(),
                    "active_tool_name": workspace.tool_name,
                    "plugin_status": "draft_ready",
                }
                try:
                    checkpoint_revision = on_checkpoint(checkpoint)
                except Exception as exc:
                    raise AgentCheckpointError("Draft checkpoint failed; retry the Agent turn") from exc
            yield _event(
                turn_id=turn_id,
                event="tool_result",
                call_id=call.id,
                name=call.name,
                ok=ok,
                summary=summary,
            )
            if changed:
                file_event = _event(
                    turn_id=turn_id,
                    event="files",
                    files=_files_payload(workspace.files),
                    preview_tool=workspace.preview_tool(),
                    messages=checkpoint_messages,
                )
                if checkpoint_revision is not None:
                    file_event["revision"] = checkpoint_revision
                yield file_event
            if call.name == "validate":
                consecutive_validation_failures = consecutive_validation_failures + 1 if not ok else 0
                if consecutive_validation_failures >= turn_limits.max_consecutive_validation_failures:
                    raise AgentBudgetExceededError("consecutive_validation_failures")
        if cancelled:
            break
        transcript.append(
            {
                "role": "assistant",
                "content": step.content or "",
                "tool_calls": tool_summaries,
            }
        )
    else:
        if not cancelled:
            raise AgentBudgetExceededError("max_iterations")

    if cancelled:
        yield _event(
            turn_id=turn_id,
            event="cancelled",
            message="Agent turn cancelled by client",
            files=_files_payload(workspace.files),
            preview_tool=workspace.preview_tool(),
        )
        yield _event(
            turn_id=turn_id,
            event="done",
            messages=transcript,
            files=_files_payload(workspace.files),
            preview_tool=workspace.preview_tool(),
            plugin_unique_identifier=None,
            installation_id=None,
            task=None,
            dirty_installed=False,
            needs_reinstall=False,
            validation_errors=[],
            cancelled=True,
        )
        return

    dirty = workspace.files != initial_files
    validation_errors: list[str] = []
    if dirty:
        try:
            from services.tool_plugin_generator.packager import normalize_plugin_source_files

            workspace.files = normalize_plugin_source_files(workspace.files)
            validate_plugin_files(workspace.files)
        except ToolPluginValidationError as exc:
            validation_errors = list(exc.errors)

    if not any(item.get("role") == "assistant" and item.get("content") for item in transcript) and final_assistant_text:
        transcript.append({"role": "assistant", "content": final_assistant_text})

    needs_reinstall = dirty
    yield _event(turn_id=turn_id, event="status", phase="done")
    yield _event(
        turn_id=turn_id,
        event="done",
        messages=transcript,
        files=_files_payload(workspace.files),
        preview_tool=workspace.preview_tool(),
        plugin_unique_identifier=None,
        installation_id=None,
        task=None,
        dirty_installed=False,
        needs_reinstall=needs_reinstall,
        validation_errors=validation_errors,
        cancelled=False,
    )


def run_agent_turn(
    *,
    message: str,
    files: dict[str, str],
    author: str,
    plugin_name: str,
    tool_name: str,
    tenant_id: str,
    user_id: str,
    llm_client: AgentLLMClient,
    history: list[dict[str, Any]] | None = None,
    has_published_version: bool = False,
    bootstrap_llm: Any | None = None,
    max_iterations: int = MAX_AGENT_ITERATIONS,
    limits: AgentTurnLimits | None = None,
    clock: Callable[[], float] = time.monotonic,
    intent: str | None = None,
    plugin_identity_locked: bool | None = None,
    on_checkpoint: Callable[[dict[str, Any]], int | None] | None = None,
) -> AgentTurnResult:
    done_event: dict[str, Any] | None = None
    for event in iter_agent_turn(
        message=message,
        files=files,
        author=author,
        plugin_name=plugin_name,
        tool_name=tool_name,
        tenant_id=tenant_id,
        user_id=user_id,
        llm_client=llm_client,
        history=history,
        has_published_version=has_published_version,
        bootstrap_llm=bootstrap_llm,
        max_iterations=max_iterations,
        limits=limits,
        clock=clock,
        intent=intent,
        plugin_identity_locked=plugin_identity_locked,
        on_checkpoint=on_checkpoint,
    ):
        if event.get("event") == "done":
            done_event = event
    if done_event is None:
        raise RuntimeError("Agent turn ended without a done event")

    files_map = {item["path"]: item["content"] for item in done_event.get("files") or []}
    return AgentTurnResult(
        messages=list(done_event.get("messages") or []),
        files=files_map,
        preview_tool=done_event.get("preview_tool"),
        plugin_unique_identifier=done_event.get("plugin_unique_identifier"),
        installation_id=done_event.get("installation_id"),
        task=done_event.get("task"),
        dirty_installed=bool(done_event.get("dirty_installed")),
        validation_errors=list(done_event.get("validation_errors") or []),
        cancelled=bool(done_event.get("cancelled")),
    )


def create_agent_llm_client(
    *,
    tenant_id: str,
    provider: str | None = None,
    model: str | None = None,
) -> TenantAgentLLMClient:
    client = TenantAgentLLMClient(
        tenant_id=tenant_id,
        provider=provider,
        model=model,
        model_manager=ModelManager.for_tenant(tenant_id=tenant_id),
    )
    client.validate_model_support()
    return client


def create_bootstrap_llm_client(
    *,
    tenant_id: str,
    provider: str | None = None,
    model: str | None = None,
) -> TenantLLMFillClient:
    return TenantLLMFillClient(
        tenant_id=tenant_id,
        provider=provider,
        model=model,
        model_manager=ModelManager.for_tenant(tenant_id=tenant_id),
    )
