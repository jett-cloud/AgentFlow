"""Typed payloads exchanged between the agent loop, its tools, and the transport.

``AgentMessage`` is the only conversation representation: an append-only list of
these rebuilt from ``WorkflowAssistMessage`` rows on every request. There is no
separate checkpoint — the message list *is* the state. Restore keeps persisted
``role`` values (``user`` / ``assistant``); ``event_type`` distinguishes a
prose ``message`` from a ``tool_call`` or ``tool_result``.

The ``Minimal*`` graph types describe the candidate graph the agent's tools build
up, which is deliberately less populated than ``GraphDict`` — see
``MinimalGraphNodeDict`` for why they are separate types rather than casts.
``AgentSession.candidate_graph`` stays a ``MinimalGraphDict`` (or a matching
dict) rather than a cast to ``GraphDict``.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

from core.workflow.generator.types import GraphViewportDict, WorkflowGenerationMode


class MinimalGraphNodeDict(TypedDict):
    """One node of the graph as the agent builds it.

    ``MinimalGraphNodeDict``, ``MinimalGraphEdgeDict``, and ``MinimalGraphDict``
    describe the graph *before* ``graph_postprocessor.postprocess_graph`` runs.
    The postprocessor is the single normaliser that fills in the ReactFlow node
    ``type`` and ``position`` and the edge ``id`` and ``type``, all of which
    ``GraphDict`` in ``core.workflow.generator.types`` declares as required.
    These types exist so the agent's own surface stays honestly typed instead of
    casting an incomplete node to ``GraphNodeDict`` — a cast that would let the
    type checker bless a ``node["position"]`` that raises ``KeyError`` at run
    time. The one legitimate conversion to ``GraphDict`` belongs at the single
    boundary that hands the finished graph to the postprocessor.
    """

    id: str
    data: dict[str, Any]
    parentId: NotRequired[str]


class MinimalGraphEdgeDict(TypedDict):
    """One edge of the graph as the agent builds it. See ``MinimalGraphNodeDict``."""

    source: str
    target: str
    sourceHandle: NotRequired[str]


class MinimalGraphDict(TypedDict):
    """The agent's in-progress graph. See ``MinimalGraphNodeDict``."""

    nodes: list[MinimalGraphNodeDict]
    edges: list[MinimalGraphEdgeDict]
    viewport: GraphViewportDict


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
