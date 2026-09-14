"""Agent session and tool protocol payloads."""

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.types import WorkflowGenerationMode


class ToolCall(TypedDict):
    """One model-requested tool invocation."""

    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(TypedDict):
    """Deterministic outcome of a tool invocation.

    ``ok`` is whether this call's goal held. ``changed`` is whether the
    candidate graph mutated — queries are always false. ``content`` is the
    short observation the model sees (never a full node config or whole-graph
    dump on ``build_node``). Failures set ``content`` to ``None`` and fill
    ``error`` / ``error_code``; ``retryable`` is looked up from the error-code
    table, never chosen ad hoc by a handler. Persisted ``tool_result`` rows
    keep whatever JSON was stored; this envelope is the live dispatch shape.
    """

    tool_call_id: str
    name: str
    ok: bool
    changed: bool
    content: dict[str, object] | None
    error: str | None
    error_code: str | None
    retryable: bool


AgentMessageEventType = Literal["message", "tool_call", "tool_result"]


AgentMessageRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class AgentMessage:
    """One persisted row in the append-only conversation.

    ``event_type`` is the row kind. ``role`` is stored as-is (``user`` /
    ``assistant``) — a ``tool_result`` is not remapped to a ``tool`` role.
    ``payload`` is the JSON body as stored; the ToolResult envelope is not
    rewritten here. A ``tool_call`` named ``ask_user`` with ``status=pending``
    and no matching ``tool_result`` is a suspended turn: the next user text
    becomes that call's result.
    """

    sequence: int
    event_type: AgentMessageEventType
    role: AgentMessageRole
    status: str
    payload: dict[str, Any]


class CandidateState(TypedDict, total=False):
    """Candidate graph and compaction fields restored beside the message list.

    Missing keys are valid: ``restore_session`` treats an empty dict as
    revision 0 with no graph. Do not cast ``graph`` to ``GraphDict``.
    """

    graph: MinimalGraphDict | dict[str, Any]
    revision: int
    base_hash: str | None
    compacted_until_sequence: int | None
    compacted_state: dict[str, Any] | None
    last_validation: dict[str, Any] | None
    contract_protocol_version: int | None
    workflow_contract: dict[str, object] | None
    contract_revision: int
    contract_hash: str | None


@dataclass
class AgentSession:
    """In-memory tool-loop session rebuilt from persisted rows plus candidate state.

    ``apply_user_turn`` returns a new session and never clears ``candidate_graph``
    or rewrites earlier payloads. Compaction fields live here so later prompt
    assembly can read the watermark without a second restore. Request-scoped
    ``edit_mode`` / ``last_run`` / canvas fields are filled by the chat
    orchestrator for ``render_current_situation``; they are not persisted.
    """

    messages: list[AgentMessage]
    candidate_graph: MinimalGraphDict | dict[str, Any] | None
    candidate_revision: int
    candidate_base_hash: str | None
    compacted_until_sequence: int | None
    compacted_state: dict[str, Any] | None
    generation_mode: WorkflowGenerationMode
    last_validation: dict[str, Any] | None
    last_acceptance: dict[str, Any] | None = None
    contract_protocol_version: int | None = None
    workflow_contract: dict[str, object] | None = None
    contract_revision: int = 0
    contract_hash: str | None = None
    edit_mode: str = "local"
    last_run: str | None = None
    canvas_graph: MinimalGraphDict | dict[str, Any] | None = None
    canvas_hash: str | None = None
    selected_node: str | None = None
    referenced_nodes: list[dict[str, Any]] = field(default_factory=list)
    referenced_tools: list[dict[str, Any]] = field(default_factory=list)
    referenced_datasets: list[dict[str, Any]] = field(default_factory=list)


AgentEventName = Literal[
    "message",
    "message.delta",
    "reasoning.delta",
    "tool_call",
    "tool_result",
    "waiting_user",
    "done",
    "failed",
    "aborted",
    "error",
    "turn_complete",
]


AgentEvent = tuple[AgentEventName, dict[str, Any]]
