"""Tool schemas, execution context, and dispatch for the workflow agent.

This module is the only place that knows tool names. The loop treats tools
opaquely: it forwards a ``ToolCall`` here and appends the returned
``ToolResult`` to the conversation.

Tool results are *always* returned — a failure is a ``ToolResult`` with
``ok=False`` and an actionable ``error_code``, never an exception. That is
what makes the agent self-correcting: a rejected call becomes an observation
the model can act on, instead of terminating the turn.

``TOOL_SCHEMAS`` is the 15-tool surface advertised to the main model.
``write_node`` / ``upsert_node`` / ``patch_node`` are not on that list;
``graph_ops.upsert_node`` remains the internal writer. ``compile_build_node``
builds config without writing the graph; ``commit_build_node`` is the writer.
``dispatch("build_node")`` still runs both in order. ``retryable`` is
looked up from ``RETRYABLE_BY_ERROR_CODE``; handlers must not set it ad hoc.

Search, ``build_node``, and ``validate_graph`` share one in-memory typed
catalogue snapshot on ``ToolContext.env``. Catalogue pull is Task 8; this
module only consumes the snapshot already on the context.

``validate_graph.ok`` means the validator ran. ``finish.ok`` means the
completion claim was accepted (fresh hydrate+validate, ``valid=true``,
revision aligned, and — when an ``AcceptanceRunner`` is injected — current
revision+hash Evidence passed). This module must not import ``services.*``;
hydrate and the runner are injected on ``ToolEnv``.
"""

from collections.abc import Callable
from typing import Any, TypedDict

from core.workflow.generator.agent.tool_context import ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.agent.tool_lifecycle import (
    ask_user,
    fail,
    finish,
    inspect_attempt,
    note_graph_mutation,
    relayout_graph,
    run_acceptance,
    validate_graph,
)
from core.workflow.generator.agent.tool_mutate import (
    CompiledBuildNode,
    build_node,
    commit_build_node,
    compile_build_node,
    connect,
    delete_node,
    disconnect,
)
from core.workflow.generator.agent.tool_read import (
    inspect_node_schema,
    read_graph,
    read_node,
    search_datasets,
    search_tools,
)
from core.workflow.generator.agent.tool_results import RETRYABLE_BY_ERROR_CODE, error
from core.workflow.generator.agent.types import ToolCall, ToolResult

__all__ = [
    "RETRYABLE_BY_ERROR_CODE",
    "TERMINAL_TOOLS",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "CompiledBuildNode",
    "ToolContext",
    "ToolEnv",
    "ToolSchema",
    "ToolTurnState",
    "commit_build_node",
    "compile_build_node",
    "dispatch",
    "note_graph_mutation",
    "relayout_graph",
]


class ToolSchema(TypedDict):
    """One tool advertised to the model."""

    name: str
    description: str
    parameters: dict[str, Any]


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_STRING: dict[str, Any] = {"type": "string"}

TOOL_SCHEMAS: list[ToolSchema] = [
    {
        "name": "read_graph",
        "description": (
            "Return the compact candidate graph: node id/type/title/parent, edges, "
            "and exposed outputs. Does not include node config. Use this to wire "
            "edges or variable references, not to edit a single node."
        ),
        "parameters": _obj({}, []),
    },
    {
        "name": "read_node",
        "description": (
            "Return one node's full editing unit including config. Does not return "
            "edges or the rest of the graph. Call this before build_node(mode=update)."
        ),
        "parameters": _obj({"id": _STRING}, ["id"]),
    },
    {
        "name": "build_node",
        "description": (
            "Create, update, or replace one node from intent. mode is required. "
            "Do not submit config; a builder writes the node JSON. "
            "update forbids type — use replace to change type."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["create", "update", "replace"]},
                "id": _STRING,
                "type": _STRING,
                "title": _STRING,
                "purpose": _STRING,
                "parent": _STRING,
            },
            "required": ["mode", "id", "purpose"],
            "allOf": [
                {
                    "if": {"properties": {"mode": {"const": "create"}}, "required": ["mode"]},
                    "then": {"required": ["type", "title"]},
                },
                {
                    "if": {"properties": {"mode": {"const": "update"}}, "required": ["mode"]},
                    "then": {"not": {"required": ["type"]}},
                },
                {
                    "if": {"properties": {"mode": {"const": "replace"}}, "required": ["mode"]},
                    "then": {"required": ["type"]},
                },
            ],
        },
    },
    {
        "name": "delete_node",
        "description": "Delete a node and every edge touching it. Missing nodes succeed with changed=false.",
        "parameters": _obj({"node_id": _STRING}, ["node_id"]),
    },
    {
        "name": "connect",
        "description": (
            "Add an edge from source to target. "
            "Pass source_handle for branching nodes, e.g. 'true' / 'false' on if-else."
        ),
        "parameters": _obj(
            {"source": _STRING, "target": _STRING, "source_handle": _STRING},
            ["source", "target"],
        ),
    },
    {
        "name": "disconnect",
        "description": (
            "Remove the matching edge. Omit source_handle when exactly one edge "
            "exists between the pair; multiple matches without a handle is an error."
        ),
        "parameters": _obj(
            {"source": _STRING, "target": _STRING, "source_handle": _STRING},
            ["source", "target"],
        ),
    },
    {
        "name": "inspect_node_schema",
        "description": "Return the legal config fields for one node type. Call when the schema is unknown or in doubt.",
        "parameters": _obj({"node_type": _STRING}, ["node_type"]),
    },
    {
        "name": "validate_graph",
        "description": (
            "Observe whether the candidate graph is structurally valid. ok means the "
            "validator ran; content.valid is whether it passed. Not required after every mutation."
        ),
        "parameters": _obj({}, []),
    },
    {
        "name": "search_datasets",
        "description": "Search the tenant's knowledge bases available in this run's catalogue snapshot.",
        "parameters": _obj({"query": _STRING}, ["query"]),
    },
    {
        "name": "search_tools",
        "description": "Search the tenant's installed tools available in this run's catalogue snapshot.",
        "parameters": _obj({"query": _STRING}, ["query"]),
    },
    {
        "name": "run_acceptance",
        "description": (
            "Run sandbox acceptance against the current candidate. Default mode is simulated: "
            "no user tools or models, usage count stays 0. mode=live requires prior ask_user "
            "consent (question id live_run_consent) and meters tools/models. "
            "ok means the runner ran; content.passed is whether cases passed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "case_ids": {"type": "array", "items": _STRING},
                "mode": {"type": "string", "enum": ["simulated", "live"]},
            },
            "required": [],
        },
    },
    {
        "name": "inspect_attempt",
        "description": (
            "Return one acceptance attempt's failed nodes and redacted I/O summary. "
            "Call after run_acceptance reports passed=false."
        ),
        "parameters": _obj({"attempt_id": _STRING}, ["attempt_id"]),
    },
    {
        "name": "ask_user",
        "description": (
            "Ask the user one or more questions and suspend until they answer. "
            "Use only when a decision genuinely changes the workflow's shape. "
            "Write questions in the user's language. "
            "When the answers are few, prefer single_choice or multi_choice with options. "
            "Do not ask about anything already answered earlier in the conversation."
        ),
        "parameters": _obj(
            {
                "questions": {
                    "type": "array",
                    "items": _obj(
                        {
                            "id": _STRING,
                            "question": _STRING,
                            "kind": {"type": "string", "enum": ["text", "single_choice", "multi_choice"]},
                            "options": {
                                "type": "array",
                                "items": _obj({"value": _STRING, "label": _STRING}, ["value", "label"]),
                            },
                        },
                        ["id", "question", "kind"],
                    ),
                }
            },
            ["questions"],
        ),
    },
    {
        "name": "fail",
        "description": (
            "End the turn as an unrecoverable business failure. Not a completion. "
            "Do not use this for a single tool error, empty search, or validation failure."
        ),
        "parameters": _obj({"reason": _STRING}, ["reason"]),
    },
    {
        "name": "finish",
        "description": (
            "Claim the workflow is done. ok means hydrate+validate passed and, when a "
            "sandbox runner is present, current-revision acceptance Evidence passed."
        ),
        "parameters": _obj({"summary": _STRING}, ["summary"]),
    },
]

TOOL_NAMES: frozenset[str] = frozenset(schema["name"] for schema in TOOL_SCHEMAS)
TERMINAL_TOOLS: frozenset[str] = frozenset({"ask_user", "fail", "finish"})

_HANDLERS: dict[str, Callable[[ToolCall, ToolContext], ToolResult]] = {
    "read_graph": read_graph,
    "read_node": read_node,
    "build_node": build_node,
    "delete_node": delete_node,
    "connect": connect,
    "disconnect": disconnect,
    "inspect_node_schema": inspect_node_schema,
    "validate_graph": validate_graph,
    "search_datasets": search_datasets,
    "search_tools": search_tools,
    "run_acceptance": run_acceptance,
    "inspect_attempt": inspect_attempt,
    "ask_user": ask_user,
    "fail": fail,
    "finish": finish,
}


def dispatch(call: ToolCall, context: ToolContext) -> ToolResult:
    """Run one tool call against ``context`` and return a ToolResult envelope.

    Unknown names and illegal arguments become ``INVALID_ARGUMENT``. Graph
    mutations rebind ``context.state.graph`` only when the call succeeds and
    ``changed`` is true, or when a successful no-op still copies the graph
    (callers may rely on identity of an unchanged graph remaining the same
    object except where graph_ops returns a deepcopy). A successful mutation
    other than ``finish`` also runs canvas layout so streamed candidates are
    not stacked at the origin. Layout failure is logged and does not turn a
    successful write into ``CAPABILITY_UNAVAILABLE``.
    """
    handler = _HANDLERS.get(call["name"])
    if handler is None:
        return error(call, "INVALID_ARGUMENT", f"Unknown tool {call['name']!r}")
    result = handler(call, context)
    # finish consumes last_mutation_changed inside its own hydrate+validate.
    # Re-setting it from finish.changed would make the next validate look like
    # a repeated repair even when nothing ran in between. Finish still runs a
    # final layout pass after hydrate (loop-start and similar).
    if result["changed"] and call["name"] != "finish":
        note_graph_mutation(context)
    return result
