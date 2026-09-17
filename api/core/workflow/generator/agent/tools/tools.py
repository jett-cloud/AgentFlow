"""Tool schemas, execution context, and dispatch for the workflow agent.

This module is the only place that knows tool names. The loop treats tools
opaquely: it forwards a ``ToolCall`` here and appends the returned
``ToolResult`` to the conversation.

Tool results are *always* returned — a failure is a ``ToolResult`` with
``ok=False`` and an actionable ``error_code``, never an exception. That is
what makes the agent self-correcting: a rejected call becomes an observation
the model can act on, instead of terminating the turn.

``TOOL_SCHEMAS`` is the public tool surface advertised to the main model.
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

from core.workflow.generator.agent.tools.tool_build_agent import (
    CompiledAgentNode,
    build_agent_node,
    commit_build_agent_node,
    compile_build_agent_node,
)
from core.workflow.generator.agent.tools.tool_build_container import (
    build_iteration,
    build_loop,
    commit_build_container,
    compile_build_iteration,
    compile_build_loop,
)
from core.workflow.generator.agent.tools.tool_build_tool import (
    CompiledToolNode,
    build_tool_node,
    commit_build_tool_node,
    compile_build_tool_node,
)
from core.workflow.generator.agent.tools.tool_context import PendingPlanNode, ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.agent.tools.tool_lifecycle import (
    ask_user,
    fail,
    finish,
    inspect_attempt,
    note_graph_mutation,
    relayout_graph,
    run_acceptance,
    validate_graph,
)
from core.workflow.generator.agent.tools.tool_mutate import (
    CompiledBuildNode,
    build_node,
    commit_build_node,
    compile_build_node,
    connect,
    delete_node,
    disconnect,
    duplicate_create_ids,
    pending_plan_nodes_from_calls,
)
from core.workflow.generator.agent.tools.tool_read import (
    activate_skills,
    inspect_node_schema,
    inspect_tool,
    list_models,
    read_graph,
    read_node,
    search_datasets,
    search_tools,
)
from core.workflow.generator.agent.tools.tool_results import RETRYABLE_BY_ERROR_CODE, error
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.compiler.intents.build_contracts import (
    BuildAgentNodeArgs,
    BuildIterationArgs,
    BuildLoopArgs,
    BuildToolNodeArgs,
    parameters_schema,
)
from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent
from core.workflow.generator.contracts.workflow_contract import (
    WorkflowPlan,
    submit_workflow_plan,
    workflow_plan_mutation_error,
)
from core.workflow.generator.prompts.loader import registered_skill_names

__all__ = [
    "RETRYABLE_BY_ERROR_CODE",
    "TERMINAL_TOOLS",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "CompiledAgentNode",
    "CompiledBuildNode",
    "CompiledToolNode",
    "PendingPlanNode",
    "ToolContext",
    "ToolEnv",
    "ToolSchema",
    "ToolTurnState",
    "commit_build_agent_node",
    "commit_build_container",
    "commit_build_node",
    "commit_build_tool_node",
    "compile_build_agent_node",
    "compile_build_iteration",
    "compile_build_loop",
    "compile_build_node",
    "compile_build_tool_node",
    "dispatch",
    "duplicate_create_ids",
    "note_graph_mutation",
    "pending_plan_nodes_from_calls",
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
_SKILL_NAMES_PARAM: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(registered_skill_names())},
    "maxItems": 4,
}


def _without_null_branch(schema: dict[str, Any]) -> dict[str, Any]:
    branches = schema.get("oneOf")
    if not isinstance(branches, list):
        return schema
    non_null = [branch for branch in branches if isinstance(branch, dict) and branch.get("type") != "null"]
    return non_null[0] if len(non_null) == 1 else schema


_STRUCTURE_SCHEMA = _without_null_branch(parameters_schema(NodeBuildIntent)["properties"]["structure"])
_TOOL_BINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"provider_name": _STRING, "tool_name": _STRING},
    "required": ["provider_name", "tool_name"],
    "additionalProperties": False,
}
_TOOL_ARGUMENT_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "const": "variable"},
                "selector": {"type": "array", "items": _STRING, "minItems": 2},
            },
            "required": ["kind", "selector"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"kind": {"type": "string", "const": "template"}, "text": _STRING},
            "required": ["kind", "text"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"kind": {"type": "string", "const": "constant"}, "value": {}},
            "required": ["kind", "value"],
            "additionalProperties": False,
        },
    ]
}
_AGENT_KNOWLEDGE_SET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": _STRING,
        "dataset_ids": {"type": "array", "items": _STRING, "minItems": 1},
        "query_mode": {"type": "string", "enum": ["generated_query", "user_query"]},
        "query_value": _STRING,
        "retrieval_mode": {"type": "string", "enum": ["multiple"]},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
        "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["dataset_ids"],
    "additionalProperties": False,
}
_AGENT_KNOWLEDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": ["replace", "clear"]},
        "sets": {"type": "array", "items": _AGENT_KNOWLEDGE_SET_SCHEMA},
    },
    "required": ["operation"],
    "additionalProperties": False,
}


def _node_output_field_schema(*, remaining_depth: int = 6) -> dict[str, Any]:
    """Return the model-visible schema for one recursively typed output field."""
    properties: dict[str, Any] = {"type": _STRING}
    if remaining_depth > 0:
        properties["children"] = {
            "type": "object",
            "additionalProperties": _node_output_field_schema(remaining_depth=remaining_depth - 1),
        }
    return _obj(properties, ["type"])


_NODE_OUTPUT_SCHEMA: dict[str, Any] = _obj(
    {
        "name": _STRING,
        "type": _STRING,
        "children": {"type": "object", "additionalProperties": _node_output_field_schema()},
    },
    ["name"],
)
_NODE_BUILD_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "objective": _STRING,
        "behavior": _STRING,
        "inputs": {
            "type": "array",
            "items": _obj(
                {"source": {"type": "array", "items": _STRING, "minItems": 2}, "role": _STRING},
                ["source", "role"],
            ),
        },
        "outputs": {"type": "array", "items": _NODE_OUTPUT_SCHEMA},
        "requirements": {"type": "array", "items": _STRING},
        "tool": {
            "type": "object",
            "properties": {
                "binding": _TOOL_BINDING_SCHEMA,
                "arguments": {"type": "object", "additionalProperties": _TOOL_ARGUMENT_SCHEMA},
            },
            "required": ["binding"],
            "additionalProperties": False,
        },
        "tool_bindings": {"type": "array", "items": _TOOL_BINDING_SCHEMA},
        "agent_knowledge": _AGENT_KNOWLEDGE_SCHEMA,
        "structure": _STRUCTURE_SCHEMA,
    },
    "required": ["objective"],
    "additionalProperties": False,
}

TOOL_SCHEMAS: list[ToolSchema] = [
    {
        "name": "submit_workflow_plan",
        "description": (
            "Create or revise the versioned workflow plan. Submit the complete replacement and the current "
            "expected_revision. This changes contract revision/hash, never graph revision."
        ),
        "parameters": _obj(
            {
                "expected_revision": {"type": "integer", "minimum": 0},
                "plan": parameters_schema(WorkflowPlan),
            },
            ["expected_revision", "plan"],
        ),
    },
    {
        "name": "read_graph",
        "description": (
            "Return the compact candidate graph: node id/type/title/parent, edges, "
            "exposed outputs, and confirmed selector/type/scope variable views. "
            "Does not include node config. Use this to wire "
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
            "Create, update, or replace one ordinary node from structured intent. mode is required. "
            "Do not submit config. Tool, Agent, Loop, and Iteration nodes have dedicated builders. "
            "For Start, End, Answer, Template, LLM, Code, and If/Else, provide intent.structure "
            "to compile required runtime fields deterministically. update forbids type — use replace to change type."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["create", "update", "replace"]},
                "id": _STRING,
                "type": _STRING,
                "title": _STRING,
                "intent": _NODE_BUILD_INTENT_SCHEMA,
                "parent": _STRING,
            },
            "required": ["mode", "id", "intent"],
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
        "name": "build_tool_node",
        "description": (
            "Create, update, or replace one Tool node from an exact catalogue binding and typed arguments. "
            "Do not submit Dify config. File parameters require a variable selector. "
            "update must not include a different implicit type — this tool always builds a Tool node."
        ),
        "parameters": parameters_schema(BuildToolNodeArgs),
    },
    {
        "name": "build_agent_node",
        "description": (
            "Create, update, or replace one Agent V2 node from a complete intent. "
            "Do not submit Dify config, Soul, or a sibling knowledge-retrieval node. "
            "Knowledge stays inside the Agent. Omit knowledge on update to keep the previous sets; "
            "use operation=clear to remove them. update must not include a different implicit type."
        ),
        "parameters": parameters_schema(BuildAgentNodeArgs),
    },
    {
        "name": "build_loop",
        "description": (
            "Create or update a Loop as one atomic subgraph: children, internal edges, "
            "loop variables, exit conditions, and public outputs. Do not submit parentId, "
            "start_node_id, or loop-start. Child refs are request-local. "
            "A child failure leaves the previous container and revision unchanged."
        ),
        "parameters": parameters_schema(BuildLoopArgs),
    },
    {
        "name": "build_iteration",
        "description": (
            "Create or update an Iteration as one atomic subgraph: children, internal edges, "
            "iterator_selector, output_selector, and aggregated public output. Do not submit "
            "parentId, start_node_id, or iteration-start. Child refs are request-local. "
            "is_parallel and parallel_nums are config fields only. "
            "A child failure leaves the previous container and revision unchanged."
        ),
        "parameters": parameters_schema(BuildIterationArgs),
    },
    {
        "name": "delete_node",
        "description": "Delete a node and every edge touching it. Missing nodes succeed with changed=false.",
        "parameters": _obj({"node_id": _STRING}, ["node_id"]),
    },
    {
        "name": "connect",
        "description": ("Add an edge from source to target. Pass source_handle: if-else case_id or 'false' for ELSE."),
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
        "name": "activate_skills",
        "description": (
            "Replace the active workflow skills. Call this alone before using "
            "instructions from those skills. The next model invocation receives "
            "their complete SKILL.md bodies."
        ),
        "parameters": _obj({"names": _SKILL_NAMES_PARAM}, ["names"]),
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
        "description": (
            "Search tenant knowledge-base names/descriptions; this does not search document contents. "
            "Use query=\"\" to browse up to 12 datasets when the name is unknown or keywords miss. "
            "catalogue_count is the total available dataset count, not the hit count. "
            "Empty hits do not mean the catalogue is empty."
        ),
        "parameters": _obj({"query": _STRING}, ["query"]),
    },
    {
        "name": "search_tools",
        "description": (
            "Search installed tool names, labels and descriptions; return at most 12 schema-free summaries. "
            "Use query=\"\" to browse when the name is unknown or keywords miss. "
            "catalogue_count counts the full run snapshot, not matches. Empty hits do not mean no tools exist."
        ),
        "parameters": _obj({"query": _STRING}, ["query"]),
    },
    {
        "name": "inspect_tool",
        "description": "Return known parameters, output names and output types for one exact tool binding.",
        "parameters": _obj(
            {"provider_name": _STRING, "tool_name": _STRING},
            ["provider_name", "tool_name"],
        ),
    },
    {
        "name": "list_models",
        "description": (
            "List available tenant LLM identities and features from the current run snapshot, 12 per page. "
            "Use the exact provider/name when building model-backed nodes. Follow next_offset for more models. "
            "available=false means discovery failed; catalogue_count=0 with available=true means none are available."
        ),
        "parameters": _obj({"offset": {"type": "integer", "minimum": 0}}, []),
    },
    {
        "name": "run_acceptance",
        "description": (
            "Run sandbox acceptance against the current candidate. Default mode is simulated: "
            "no user tools or models, usage count stays 0. mode=live requires prior ask_user "
            "consent (question id live_run_consent) and meters tools/models. "
            "ok means the runner ran; content.passed is whether cases passed. "
            "content.executed is true only when GraphEngine actually ran; unexecuted_node_ids "
            "lists coverage gaps. runtime_contract_passed and business_verified are separate. "
            "Simulated passed is not proof of business correctness. "
            "Hydrates inline Agent bindings before recording Evidence."
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
    "submit_workflow_plan": submit_workflow_plan,
    "read_graph": read_graph,
    "read_node": read_node,
    "build_node": build_node,
    "build_tool_node": build_tool_node,
    "build_agent_node": build_agent_node,
    "build_loop": build_loop,
    "build_iteration": build_iteration,
    "delete_node": delete_node,
    "connect": connect,
    "disconnect": disconnect,
    "inspect_node_schema": inspect_node_schema,
    "activate_skills": activate_skills,
    "validate_graph": validate_graph,
    "search_datasets": search_datasets,
    "search_tools": search_tools,
    "list_models": list_models,
    "inspect_tool": inspect_tool,
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
    other than ``finish`` or ``run_acceptance`` also runs canvas layout so
    streamed candidates are not stacked at the origin. ``run_acceptance``
    hydrates and lays out before hashing Evidence; a later layout here would
    invalidate that hash. Layout failure is logged and does not turn a
    successful write into ``CAPABILITY_UNAVAILABLE``.
    """
    handler = _HANDLERS.get(call["name"])
    if handler is None:
        return error(call, "INVALID_ARGUMENT", f"Unknown tool {call['name']!r}")
    plan_error = workflow_plan_mutation_error(call, context)
    if plan_error is not None:
        return plan_error
    result = handler(call, context)
    # finish consumes last_mutation_changed inside its own hydrate+validate.
    # Re-setting it from finish.changed would make the next validate look like
    # a repeated repair even when nothing ran in between. Finish still runs a
    # final layout pass after hydrate (loop-start and similar).
    # run_acceptance hydrates/lays out before Evidence; skip a second layout.
    if result["changed"] and call["name"] not in {"finish", "run_acceptance"}:
        note_graph_mutation(context)
    return result
