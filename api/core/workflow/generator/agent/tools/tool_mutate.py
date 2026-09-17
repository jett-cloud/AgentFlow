"""Graph-mutating tools: build_node, delete, connect, disconnect.

``compile_build_node`` builds config without writing the graph;
``commit_build_node`` is the writer. ``dispatch("build_node")`` still runs both
in order. Parallel create only overlaps compile.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from core.workflow.generator.agent.tools.tool_context import PendingPlanNode, ToolContext
from core.workflow.generator.agent.tools.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.compiler.agent_knowledge import (
    collect_agent_knowledge_dataset_ids,
)
from core.workflow.generator.compiler.intents.node_intent import (
    parse_node_build_intent,
    render_node_builder_spec,
)
from core.workflow.generator.compiler.node_builder import build_single_node
from core.workflow.generator.compiler.ordinary_node_compiler import compile_structured_node_config
from core.workflow.generator.graph.graph_ops import (
    confirmed_variable_views,
    find_node,
    upsert_node,
)
from core.workflow.generator.graph.graph_ops import (
    connect as connect_edge,
)
from core.workflow.generator.graph.graph_ops import (
    delete_node as remove_node,
)
from core.workflow.generator.graph.graph_ops import (
    disconnect as disconnect_edge,
)
from core.workflow.generator.graph.id_policy import validate_mutation_node_id
from core.workflow.generator.graph.types import MinimalGraphNodeDict
from core.workflow.generator.model_io.budget import (
    ModelCallBudgetExceededError,
    RunCancelledError,
    budgeted_llm_json_client,
)
from core.workflow.generator.validation.intent_config_validator import (
    validate_intent_reference_nodes,
    validate_node_config_against_intent,
)
from core.workflow.generator.validation.node_config_validator import (
    collect_generated_node_completeness_errors,
    collect_node_config_errors,
)
from core.workflow.generator.variables.declarations import declared_outputs
from core.workflow.generator.variables.syntax import collect_references

logger = logging.getLogger(__name__)

_CONTAINER_TYPES = frozenset({"iteration", "loop"})
_BUILD_MODES = frozenset({"create", "update", "replace"})
_MECHANICAL_CONFIG_ERROR_CODES = frozenset({"INVALID_NODE_CONFIG", "INVALID_JSON"})
_SPECIALIZED_BUILD_NODE_ERRORS: dict[str, tuple[str, str]] = {
    "tool": ("TOOL_NODE_REQUIRES_BUILD_TOOL_NODE", "Use build_tool_node for Tool nodes"),
    "agent": ("AGENT_NODE_REQUIRES_BUILD_AGENT_NODE", "Use build_agent_node for Agent nodes"),
    "loop": ("CONTAINER_REQUIRES_BUILD_LOOP", "Use build_loop for Loop containers"),
    "iteration": ("CONTAINER_REQUIRES_BUILD_ITERATION", "Use build_iteration for Iteration containers"),
}
_EFFECT_KEYS: dict[str, str] = {
    "model": "model",
    "prompt": "prompt",
    "prompt_template": "prompt",
    "answer": "prompt",
    "template": "prompt",
    "agent_task": "prompt",
    "structured_output": "structured_output",
    "dataset_ids": "dataset_binding",
    "knowledge": "dataset_binding",
    "provider_id": "tool_binding",
    "provider_name": "tool_binding",
    "tool_name": "tool_binding",
    "variables": "variables",
}

_OUTPUTS_HEADING = re.compile(
    r"(?is)outputs:\s*(.*?)(?=\s*(?:objective|inputs|behavior|variable references|"
    r"resource bindings|configuration constraints|fields to preserve):|$)"
)
_OUTPUT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_purpose_output_names(purpose: str) -> tuple[str, ...]:
    """Best-effort identifiers from an ``Outputs:`` heading. Never rejects."""
    match = _OUTPUTS_HEADING.search(purpose)
    if match is None:
        return ()
    raw = match.group(1).strip()
    if not raw or raw.lower() == "none":
        return ()
    names: list[str] = []
    seen: set[str] = set()
    for name in _OUTPUT_NAME.findall(raw):
        if name.lower() == "none" or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def provisional_outputs_for_pending(node_type: str, purpose: str) -> tuple[str, ...]:
    parsed = parse_purpose_output_names(purpose)
    if parsed:
        return parsed
    return tuple(declared_outputs({"id": "_", "data": {"type": node_type}}))


_PENDING_TYPES_BY_TOOL = {
    "build_tool_node": "tool",
    "build_agent_node": "agent",
    "build_loop": "loop",
    "build_iteration": "iteration",
}


def pending_plan_nodes_from_calls(calls: Sequence[ToolCall]) -> tuple[PendingPlanNode, ...]:
    nodes: list[PendingPlanNode] = []
    for call in calls:
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        node_id = arguments.get("id")
        node_type = arguments.get("type")
        if not isinstance(node_type, str) or not node_type:
            implied = _PENDING_TYPES_BY_TOOL.get(str(call.get("name") or ""))
            node_type = implied
        if not isinstance(node_id, str) or not node_id or not isinstance(node_type, str) or not node_type:
            continue
        title = arguments.get("title")
        raw_intent = arguments.get("intent")
        parent = arguments.get("parent")
        objective, outputs = _pending_intent_summary(raw_intent)
        iterator_input_type: str | None = None
        if node_type == "iteration":
            raw_iterator = arguments.get("iterator_input_type")
            if isinstance(raw_iterator, str) and raw_iterator:
                iterator_input_type = raw_iterator
        nodes.append(
            PendingPlanNode(
                id=node_id,
                type=node_type,
                title=title if isinstance(title, str) and title else node_id,
                purpose=objective,
                parent=parent if isinstance(parent, str) and parent else None,
                provisional_outputs=outputs or tuple(declared_outputs({"id": "_", "data": {"type": node_type}})),
                iterator_input_type=iterator_input_type,
            )
        )
    return tuple(nodes)


def _pending_intent_summary(raw: object) -> tuple[str, tuple[str, ...]]:
    """Read only the batch-planning fields; malformed calls are rejected during compile."""
    if not isinstance(raw, dict):
        return "", ()
    objective = raw.get("objective")
    raw_outputs = raw.get("outputs")
    outputs: list[str] = []
    if isinstance(raw_outputs, list):
        for item in raw_outputs:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str) and name and name not in outputs:
                outputs.append(name)
    return (objective if isinstance(objective, str) else ""), tuple(outputs)


def duplicate_create_ids(calls: Sequence[ToolCall]) -> frozenset[str]:
    counts: dict[str, int] = {}
    for call in calls:
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        node_id = arguments.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        counts[node_id] = counts.get(node_id, 0) + 1
    return frozenset(node_id for node_id, count in counts.items() if count > 1)


def extra_plan_nodes_from_pending(pending: tuple[PendingPlanNode, ...]) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    for node in pending:
        extra: dict[str, Any] = {
            "id": node.id,
            "node_type": node.type,
            "label": node.title,
            "purpose": node.purpose,
            "outputs": list(node.provisional_outputs),
            "outputs_kind": "provisional",
        }
        if node.parent:
            extra["parent"] = node.parent
        extras.append(extra)
    return extras


def _parent_allowed(parent: str, node_id: str, context: ToolContext) -> bool:
    live = find_node(context.state.graph, parent)
    if live is not None:
        return str(live["data"].get("type") or "") in _CONTAINER_TYPES
    parent_index: int | None = None
    current_index: int | None = None
    parent_type: str | None = None
    for index, pending in enumerate(context.state.pending_plan_nodes):
        if pending.id == parent:
            parent_index = index
            parent_type = pending.type
        if pending.id == node_id:
            current_index = index
    if parent_index is None or current_index is None or parent_type not in _CONTAINER_TYPES:
        return False
    return parent_index < current_index


def _ancestor_ids_from_parent(
    parent: str | None,
    nodes_by_id: dict[str, dict[str, object]],
    pending_parent_by_id: dict[str, str | None] | None = None,
) -> set[str]:
    ancestors: set[str] = set()
    current_id = parent
    pending_parent_by_id = pending_parent_by_id or {}
    while current_id is not None and current_id not in ancestors and len(ancestors) < 64:
        ancestors.add(current_id)
        current = nodes_by_id.get(current_id)
        if current is not None:
            data = current.get("data")
            data_parent = data.get("parentId") if isinstance(data, dict) else None
            raw_parent = data_parent or current.get("parentId")
            current_id = raw_parent if isinstance(raw_parent, str) and raw_parent else None
            continue
        pending_parent = pending_parent_by_id.get(current_id)
        current_id = pending_parent if isinstance(pending_parent, str) and pending_parent else None
    return ancestors


@dataclass(frozen=True)
class CompiledBuildNode:
    """Validated ``build_node`` work that has not been written to the graph yet.

    ``compile_build_node`` may call the node-builder LLM. It must not rebind
    ``context.state.graph``. ``commit_build_node`` is the only writer. ``dispatch``
    still runs compile then commit on one call; later parallel create only
    overlaps compile.
    """

    call: ToolCall
    node_id: str
    node_type: str
    title: str
    desc: str
    config: dict[str, Any]
    parent: str | None
    mode: str
    old_config: dict[str, Any]
    old_parent: str | None


def compile_build_node(call: ToolCall, context: ToolContext) -> CompiledBuildNode | ToolResult:
    """Validate arguments and build node config without mutating ``context.state.graph``."""
    arguments = call["arguments"]
    mode = arguments.get("mode")
    if not isinstance(mode, str) or mode not in _BUILD_MODES:
        return error(call, "INVALID_ARGUMENT", "mode must be create, update, or replace")
    node_id = require_str(arguments, "id")
    if node_id is None:
        return error(call, "INVALID_ARGUMENT", "id is required")
    try:
        node_id = validate_mutation_node_id(node_id)
    except ValueError as exc:
        return error(call, "INVALID_NODE_ID", str(exc))
    if mode == "update" and "type" in arguments:
        return error(call, "INVALID_ARGUMENT", "update must not include type; use replace to change type")

    existing = find_node(context.state.graph, node_id)
    if mode == "create" and existing is not None:
        return error(call, "NODE_EXISTS", f"Node {node_id!r} already exists")
    if mode in {"update", "replace"} and existing is None:
        return error(call, "NODE_NOT_FOUND", f"Node {node_id!r} does not exist")

    requested_type = arguments.get("type")
    if mode in {"create", "replace"}:
        if not isinstance(requested_type, str) or not requested_type:
            return error(call, "INVALID_ARGUMENT", "type is required")
        node_type = requested_type
    else:
        assert existing is not None
        node_type = str(existing["data"].get("type") or "")

    if mode == "replace" and existing is not None and str(existing["data"].get("type") or "") == node_type:
        return error(call, "TYPE_UNCHANGED_USE_UPDATE", "replace requires a different type; use update")

    specialized = _SPECIALIZED_BUILD_NODE_ERRORS.get(node_type)
    if specialized is not None:
        return error(call, specialized[0], specialized[1])

    if mode == "create" and not require_str(arguments, "title"):
        return error(call, "INVALID_ARGUMENT", "title is required when creating a node")

    try:
        intent = parse_node_build_intent(node_type=node_type, raw=arguments.get("intent"))
    except ValidationError as exc:
        return error(call, "INVALID_ARGUMENT", _intent_validation_detail(exc))
    except ValueError as exc:
        return error(call, "INVALID_ARGUMENT", str(exc))

    parent, parent_error = _resolve_parent(mode, arguments, existing)
    if parent_error is not None:
        return error(call, parent_error, "parent is invalid")
    if parent is not None:
        if not _parent_allowed(parent, node_id, context):
            return error(call, "INVALID_PARENT", f"Parent {parent!r} is not an existing container")

    reference_issues = validate_intent_reference_nodes(
        intent=intent,
        graph=context.state.graph,
        pending_nodes=context.state.pending_plan_nodes,
    )
    if reference_issues:
        first = reference_issues[0]
        return error(call, first.code, first.detail, path=first.field_path, cause=first.cause())

    title = _resolve_title(mode, arguments, existing)
    desc = str(existing["data"].get("desc") or "") if existing is not None else ""
    old_config = _node_config(existing) if existing is not None else {}
    old_parent = _existing_parent(existing)

    builder_spec = render_node_builder_spec(intent, node_type=node_type)
    builder_input = context.env.builder_input

    def invoke_builder(purpose: str) -> dict[str, Any]:
        return build_single_node(
            client=budgeted_llm_json_client(context.env.llm_client, context.state.model_call_budget),
            request=builder_input,
            node_id=node_id,
            node_type=node_type,
            title=title,
            purpose=purpose,
            existing_node=dict(existing) if existing is not None else None,
            extra_plan_nodes=extra_plan_nodes_from_pending(context.state.pending_plan_nodes),
            topology_graph=dict(context.state.graph),
        )

    # Builder/LLM failures must bounce as a ToolResult; never leave a half-written node.
    builder_repaired = False
    if intent.structure is not None:
        config = old_config if mode == "update" else {}
    else:
        try:
            config = invoke_builder(builder_spec)
        except RunCancelledError:
            return error(call, "RUN_ABORTED", "Run cancelled before node Builder completed")
        except ModelCallBudgetExceededError:
            return error(call, "MODEL_CALL_BUDGET_EXHAUSTED", "Agent model-call limit reached")
        except Exception:
            logger.exception("Workflow agent: node builder failed for %s", node_id)
            return error(call, "CAPABILITY_UNAVAILABLE", "Node builder failed")

    config = compile_structured_node_config(intent=intent, builder_config=config)

    membership_error = _snapshot_membership_error(call, context, config)
    if membership_error is not None:
        return membership_error

    config_error = _node_config_error(
        call,
        node_id=node_id,
        node_type=node_type,
        title=title,
        config=config,
    )
    if (
        config_error is not None
        and intent.structure is None
        and config_error["error_code"] in _MECHANICAL_CONFIG_ERROR_CODES
    ):
        repair_spec = (
            f"{builder_spec}\nRepair feedback:\n"
            f"- {config_error['error_code']}: {config_error['error']}\n"
            "Return one complete replacement config that satisfies the same intent."
        )
        try:
            config = invoke_builder(repair_spec)
        except RunCancelledError:
            return error(call, "RUN_ABORTED", "Run cancelled before node Builder repair")
        except ModelCallBudgetExceededError:
            return error(call, "MODEL_CALL_BUDGET_EXHAUSTED", "Agent model-call limit reached")
        except Exception:
            logger.exception("Workflow agent: node builder repair failed for %s", node_id)
            return error(call, "CAPABILITY_UNAVAILABLE", "Node builder repair failed")
        builder_repaired = True
        config = compile_structured_node_config(intent=intent, builder_config=config)
        membership_error = _snapshot_membership_error(call, context, config)
        if membership_error is not None:
            return membership_error
        config_error = _node_config_error(
            call,
            node_id=node_id,
            node_type=node_type,
            title=title,
            config=config,
        )
    if config_error is not None:
        return config_error
    intent_issues = validate_node_config_against_intent(
        node_id=node_id,
        node_type=node_type,
        title=title,
        intent=intent,
        config=config,
    )
    if intent_issues and intent.structure is None and not builder_repaired:
        first = intent_issues[0]
        repair_spec = (
            f"{builder_spec}\nRepair feedback:\n"
            f"- {first.code}: {first.detail}\n"
            "Return one complete replacement config that satisfies the same intent."
        )
        try:
            config = invoke_builder(repair_spec)
        except RunCancelledError:
            return error(call, "RUN_ABORTED", "Run cancelled before node Builder repair")
        except ModelCallBudgetExceededError:
            return error(call, "MODEL_CALL_BUDGET_EXHAUSTED", "Agent model-call limit reached")
        except Exception:
            logger.exception("Workflow agent: node builder repair failed for %s", node_id)
            return error(call, "CAPABILITY_UNAVAILABLE", "Node builder repair failed")
        config = compile_structured_node_config(intent=intent, builder_config=config)
        membership_error = _snapshot_membership_error(call, context, config)
        if membership_error is not None:
            return membership_error
        config_error = _node_config_error(
            call,
            node_id=node_id,
            node_type=node_type,
            title=title,
            config=config,
        )
        if config_error is not None:
            return config_error
        intent_issues = validate_node_config_against_intent(
            node_id=node_id,
            node_type=node_type,
            title=title,
            intent=intent,
            config=config,
        )
    if intent_issues:
        first = intent_issues[0]
        return error(call, first.code, first.detail, path=first.field_path, cause=first.cause())

    return CompiledBuildNode(
        call=call,
        node_id=node_id,
        node_type=node_type,
        title=title,
        desc=desc,
        config=config,
        parent=parent,
        mode=str(mode),
        old_config=old_config,
        old_parent=old_parent,
    )


def _intent_validation_detail(exc: ValidationError) -> str:
    """Return one safe field path without echoing the rejected payload."""
    first = exc.errors(include_input=False)[0]
    path = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg") or "invalid value")
    return f"intent.{path}: {message}" if path else f"intent: {message}"


def commit_build_node(compiled: CompiledBuildNode, context: ToolContext) -> ToolResult:
    """Write a compiled ``build_node`` onto ``context.state.graph``."""
    context.state.graph = upsert_node(
        context.state.graph,
        node_id=compiled.node_id,
        node_type=compiled.node_type,
        title=compiled.title,
        desc=compiled.desc,
        config=compiled.config,
        parent=compiled.parent,
    )
    content = _build_node_content(
        node_id=compiled.node_id,
        node_type=compiled.node_type,
        title=compiled.title,
        parent=compiled.parent,
        mode=compiled.mode,
        old_config=compiled.old_config,
        new_config=compiled.config,
        old_parent=compiled.old_parent,
        edges=context.state.graph["edges"],
    )
    return ok(compiled.call, changed=True, content=content)


def build_node(call: ToolCall, context: ToolContext) -> ToolResult:
    compiled = compile_build_node(call, context)
    if isinstance(compiled, CompiledBuildNode):
        return commit_build_node(compiled, context)
    return compiled


def delete_node(call: ToolCall, context: ToolContext) -> ToolResult:
    node_id = require_str(call["arguments"], "node_id")
    if node_id is None:
        return error(call, "INVALID_ARGUMENT", "node_id is required")
    if find_node(context.state.graph, node_id) is None:
        return ok(call, changed=False, content={"reason": "node_not_present"})
    context.state.graph = remove_node(context.state.graph, node_id)
    return ok(call, changed=True, content={"id": node_id})


def connect(call: ToolCall, context: ToolContext) -> ToolResult:
    source = require_str(call["arguments"], "source")
    target = require_str(call["arguments"], "target")
    if source is None or target is None:
        return error(call, "INVALID_ARGUMENT", "source and target are required")
    if find_node(context.state.graph, source) is None or find_node(context.state.graph, target) is None:
        return error(call, "NODE_NOT_FOUND", "Both endpoints must exist")
    handle = call["arguments"].get("source_handle")
    source_handle = handle if isinstance(handle, str) else None
    before = len(context.state.graph["edges"])
    context.state.graph = connect_edge(context.state.graph, source=source, target=target, source_handle=source_handle)
    if len(context.state.graph["edges"]) == before:
        return ok(call, changed=False, content={"reason": "edge_already_exists"})
    content: dict[str, object] = {"source": source, "target": target}
    if source_handle:
        content["source_handle"] = source_handle
    return ok(call, changed=True, content=content)


def disconnect(call: ToolCall, context: ToolContext) -> ToolResult:
    source = require_str(call["arguments"], "source")
    target = require_str(call["arguments"], "target")
    if source is None or target is None:
        return error(call, "INVALID_ARGUMENT", "source and target are required")
    handle = call["arguments"].get("source_handle")
    source_handle = handle if isinstance(handle, str) else None
    graph, match_count = disconnect_edge(context.state.graph, source=source, target=target, source_handle=source_handle)
    if source_handle in (None, "") and match_count > 1:
        return error(call, "AMBIGUOUS_EDGE", "Pass source_handle to choose which edge to remove")
    if match_count == 0:
        return ok(call, changed=False, content={"reason": "edge_not_present"})
    context.state.graph = graph
    return ok(call, changed=True, content={"source": source, "target": target})


def _resolve_parent(
    mode: str,
    arguments: dict[str, Any],
    existing: MinimalGraphNodeDict | None,
) -> tuple[str | None, str | None]:
    if "parent" not in arguments:
        if mode == "create" or existing is None:
            return None, None
        return _existing_parent(existing), None
    parent = arguments.get("parent")
    if parent is None or parent == "":
        return None, None
    if not isinstance(parent, str):
        return None, "INVALID_ARGUMENT"
    return parent, None


def _resolve_title(mode: str, arguments: dict[str, Any], existing: MinimalGraphNodeDict | None) -> str:
    title = arguments.get("title")
    if isinstance(title, str) and title:
        return title
    if existing is not None:
        return str(existing["data"].get("title") or existing["id"])
    return str(arguments.get("id") or "")


def _existing_parent(existing: MinimalGraphNodeDict | None) -> str | None:
    if existing is None:
        return None
    parent = existing.get("parentId") or existing["data"].get("parentId")
    if isinstance(parent, str) and parent:
        return parent
    return None


def _node_config(node: MinimalGraphNodeDict) -> dict[str, Any]:
    return {key: value for key, value in node["data"].items() if key not in {"type", "title", "desc", "parentId"}}


def _build_node_content(
    *,
    node_id: str,
    node_type: str,
    title: str,
    parent: str | None,
    mode: str,
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    old_parent: str | None,
    edges: list[Any],
) -> dict[str, object]:
    content: dict[str, object] = {
        "id": node_id,
        "type": node_type,
        "title": title,
        "mode": mode,
        "effects": _config_effects(
            old_config,
            new_config,
            type_changed=mode == "replace",
            parent_changed=old_parent != parent,
        ),
        "bindings": sorted(f"{source_id}.{var}" for source_id, var in collect_references(new_config)),
        "resources": _collect_resources(new_config),
    }
    node: MinimalGraphNodeDict = {
        "id": node_id,
        "data": {**new_config, "type": node_type, "title": title},
    }
    if parent:
        node["parentId"] = parent
    content["variables"] = confirmed_variable_views(node)
    if parent:
        content["parent"] = parent
    if mode == "replace":
        content["preserved_edge_count"] = sum(
            1 for edge in edges if edge.get("source") == node_id or edge.get("target") == node_id
        )
        content["requires_revalidation"] = True
    return content


def _config_effects(
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    *,
    type_changed: bool,
    parent_changed: bool,
) -> list[str]:
    effects: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            effects.append(name)

    if type_changed:
        add("type")
    if parent_changed:
        add("parent")
    for key in sorted(set(old_config) | set(new_config)):
        if old_config.get(key) == new_config.get(key):
            continue
        mapped = _EFFECT_KEYS.get(key)
        if mapped:
            add(mapped)
    return effects


def _snapshot_membership_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    """Reject builder config that names a resource outside this run's snapshot.

    ``available=false`` / ``installed_*=None`` skips that side. An empty set is
    "the tenant has none", so every id is unknown. Cross-namespace reuse uses
    the same ``UNKNOWN_DATASET`` / ``UNKNOWN_TOOL`` codes as the field kind.
    """
    dataset_error = _unknown_dataset_error(call, context, config)
    if dataset_error is not None:
        return dataset_error
    return _unknown_tool_error(call, context, config)


def _unknown_dataset_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    if not context.env.knowledge_available or context.env.installed_dataset_ids is None:
        return None
    raw_dataset_ids = config.get("dataset_ids")
    dataset_ids = (
        [item for item in raw_dataset_ids if isinstance(item, str)] if isinstance(raw_dataset_ids, list) else []
    )
    dataset_ids.extend(collect_agent_knowledge_dataset_ids(config))
    unknown = [item for item in dataset_ids if isinstance(item, str) and item not in context.env.installed_dataset_ids]
    if not unknown:
        return None
    return error(
        call,
        "UNKNOWN_DATASET",
        f"Dataset {unknown[0]!r} is not in this run's knowledge snapshot",
    )


def _unknown_tool_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    if not context.env.tools_available or context.env.installed_tools is None:
        return None
    provider = config.get("provider_id") or config.get("provider_name")
    tool_name = config.get("tool_name")
    if isinstance(provider, str) and isinstance(tool_name, str) and provider and tool_name:
        if (provider, tool_name) not in context.env.installed_tools:
            return error(
                call,
                "UNKNOWN_TOOL",
                f"Tool {provider}/{tool_name} is not in this run's tool snapshot",
            )
    return _unknown_dify_tools_error(call, context, config)


def _unknown_dify_tools_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    dify_tools = config.get("dify_tools")
    if not isinstance(dify_tools, list) or context.env.installed_tools is None:
        return None
    providers = {item[0] for item in context.env.installed_tools}
    for item in dify_tools:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider_id") or item.get("provider_name") or item.get("provider")
        if not isinstance(provider, str) or not provider:
            continue
        tool_name = item.get("tool_name")
        if tool_name is None or tool_name == "":
            if provider not in providers:
                return error(
                    call,
                    "UNKNOWN_TOOL",
                    f"Tool {provider} is not in this run's tool snapshot",
                )
            continue
        if not isinstance(tool_name, str):
            continue
        if (provider, tool_name) not in context.env.installed_tools:
            return error(
                call,
                "UNKNOWN_TOOL",
                f"Tool {provider}/{tool_name} is not in this run's tool snapshot",
            )
    return None


def _apply_agent_binding_ids(*, mode: str, config: dict[str, Any], old_config: dict[str, Any]) -> None:
    """Keep trusted update ids; drop Builder-invented ids on create/replace.

    create/replace always discard ``agent_id`` / ``current_snapshot_id`` from the
    Builder payload. update restores those fields from the existing node so a
    later hydrate can refresh the same Agent snapshot instead of minting a new
    Agent.
    """
    binding = config.get("agent_binding")
    if not isinstance(binding, dict):
        return
    binding.pop("agent_id", None)
    binding.pop("current_snapshot_id", None)
    if mode != "update":
        return
    old_binding = old_config.get("agent_binding")
    if not isinstance(old_binding, dict):
        return
    agent_id = old_binding.get("agent_id")
    snapshot_id = old_binding.get("current_snapshot_id")
    if isinstance(agent_id, str) and agent_id.strip():
        binding["agent_id"] = agent_id
    if isinstance(snapshot_id, str) and snapshot_id.strip():
        binding["current_snapshot_id"] = snapshot_id


def _node_config_error(
    call: ToolCall,
    *,
    node_id: str,
    node_type: str,
    title: str,
    config: dict[str, Any],
) -> ToolResult | None:
    wrapped = {**config, "type": node_type, "title": title}
    errors = collect_node_config_errors([{"id": node_id, "data": wrapped}])
    if not errors:
        errors = collect_generated_node_completeness_errors([{"id": node_id, "data": wrapped}])
    if not errors:
        return None
    first = errors[0]
    return error(call, str(first["code"]), first["detail"])


def _collect_resources(config: dict[str, Any]) -> list[str]:
    resources: list[str] = []
    dataset_ids = config.get("dataset_ids")
    if isinstance(dataset_ids, list):
        resources.extend(f"dataset:{item}" for item in dataset_ids if isinstance(item, str))
    resources.extend(f"dataset:{item}" for item in collect_agent_knowledge_dataset_ids(config))
    provider = config.get("provider_name") or config.get("provider_id")
    tool_name = config.get("tool_name")
    if isinstance(provider, str) and isinstance(tool_name, str) and provider and tool_name:
        resources.append(f"tool:{provider}/{tool_name}")
    return resources
