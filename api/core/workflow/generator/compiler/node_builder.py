"""Parallel per-node building and planner graph assembly."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from configs import dify_config
from core.workflow.generator.graph.container_nodes import CONTAINER_NODE_TYPES, resolve_container_start_node_id
from core.workflow.generator.model_io.llm_response import LLMJsonClient, StageSchemaError
from core.workflow.generator.prompts.node_builder_prompts import (
    NODE_BUILDER_USER_PROMPT,
    format_mode_section,
    format_parallel_plan,
    format_start_inputs_section,
    get_node_builder_system_prompt,
)
from core.workflow.generator.prompts.node_builder_prompts import (
    format_knowledge_catalogue_section as format_node_knowledge_catalogue_section,
)
from core.workflow.generator.prompts.node_builder_prompts import (
    format_tool_catalogue_section as format_node_tool_catalogue_section,
)
from core.workflow.generator.prompts.output_language import (
    OutputLanguage,
    localized_generator_message,
    output_language_name,
    text_matches_output_language,
)
from core.workflow.generator.prompts.planner_prompts import format_ideal_output_section
from core.workflow.generator.types import GraphDict, WorkflowGenerationMode
from core.workflow.generator.variables.declarations import declared_outputs
from graphon.enums import BuiltinNodeTypes
from graphon.model_runtime.entities.message_entities import SystemPromptMessage, UserPromptMessage

_DEFAULT_VIEWPORT = {"x": 0.0, "y": 0.0, "zoom": 0.7}
_MODEL_NODE_TYPES = frozenset(
    {
        BuiltinNodeTypes.LLM,
        BuiltinNodeTypes.QUESTION_CLASSIFIER,
        BuiltinNodeTypes.PARAMETER_EXTRACTOR,
        BuiltinNodeTypes.AGENT,
    }
)
_SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credential_id",
        "credentials",
        "headers",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)

GenerationEvent = tuple[str, dict[str, Any]]
GenerationEventSink = Callable[[GenerationEvent], None]
_LANGUAGE_RETRY_HINT = (
    "Your previous config used the wrong language for user-visible text. "
    "Return the same JSON shape again, with every natural-language prompt, reply, label, and instruction "
    "written in the requested output language. Keep code, ids, selectors, URLs, schema keys, and tool identifiers "
    "unchanged."
)


@dataclass(frozen=True)
class BuilderInput:
    provider: str
    model_name: str
    model_mode: str
    mode: WorkflowGenerationMode
    instruction: str
    ideal_output: str
    plan_nodes: list[dict[str, Any]]
    plan_edges: list[dict[str, Any]]
    tool_catalogue_text: str
    knowledge_catalogue_text: str
    start_inputs: list[dict[str, Any]]
    current_graph: dict[str, Any] | None
    output_language: OutputLanguage


def _node_builder_max_workers() -> int:
    return dify_config.WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS


def _is_sensitive_config_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_CONFIG_KEYS or normalized.endswith(("_api_key", "_password", "_secret", "_token"))


def _sanitize_existing_config_for_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_existing_config_for_prompt(item)
            for key, item in value.items()
            if not isinstance(key, str) or not _is_sensitive_config_key(key)
        }
    if isinstance(value, list):
        return [_sanitize_existing_config_for_prompt(item) for item in value]
    return deepcopy(value)


def _start_inputs_from_graph(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(graph, dict):
        return []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if data.get("type") != BuiltinNodeTypes.START:
            continue
        return [
            variable
            for variable in (data.get("variables") or [])
            if isinstance(variable, dict) and isinstance(variable.get("variable"), str) and variable["variable"]
        ]
    return []


def _builder_topology_plan(
    graph: dict[str, Any] | None,
    *,
    target_node: dict[str, Any],
    extra_plan_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compact live topology plus same-batch pending nodes. Live edges only."""
    plan_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    plan_edges: list[dict[str, Any]] = []
    if isinstance(graph, dict):
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
                continue
            node_id = node["id"]
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            item: dict[str, Any] = {
                "id": node_id,
                "node_type": str(data.get("type") or ""),
                "label": str(data.get("title") or node_id),
                "outputs": declared_outputs(node),
                "outputs_kind": "confirmed",
            }
            parent = node.get("parentId") or data.get("parentId")
            if isinstance(parent, str) and parent:
                item["parent"] = parent
            plan_nodes.append(item)
            seen.add(node_id)
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            source = edge.get("source")
            target = edge.get("target")
            if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
                continue
            compact: dict[str, Any] = {"source": source, "target": target}
            handle = edge.get("sourceHandle") or edge.get("source_handle")
            if isinstance(handle, str) and handle:
                compact["source_handle"] = handle
            plan_edges.append(compact)
    for extra in extra_plan_nodes:
        extra_id = str(extra.get("id") or "")
        if not extra_id or extra_id in seen:
            continue
        item = {
            "id": extra_id,
            "node_type": str(extra.get("node_type") or extra.get("type") or ""),
            "label": str(extra.get("label") or extra.get("title") or extra_id),
            "outputs": [name for name in (extra.get("outputs") or []) if isinstance(name, str) and name],
            "outputs_kind": extra.get("outputs_kind") or "provisional",
        }
        purpose = extra.get("purpose")
        if isinstance(purpose, str) and purpose:
            item["purpose"] = purpose
        parent = extra.get("parent")
        if isinstance(parent, str) and parent:
            item["parent"] = parent
        plan_nodes.append(item)
        seen.add(extra_id)
    target_id = str(target_node.get("id") or "")
    if target_id and target_id not in seen:
        plan_nodes.append(
            {
                "id": target_id,
                "node_type": str(target_node.get("node_type") or ""),
                "label": str(target_node.get("label") or target_id),
                "purpose": str(target_node.get("purpose") or ""),
                "outputs": [],
                "outputs_kind": "provisional",
            }
        )
    return plan_nodes, plan_edges


def _merge_generated_config(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, generated_value in generated.items():
        if _is_sensitive_config_key(key) and key in existing:
            continue
        existing_value = existing.get(key)
        if isinstance(existing_value, dict) and isinstance(generated_value, dict):
            merged[key] = _merge_generated_config(existing_value, generated_value)
        else:
            merged[key] = deepcopy(generated_value)
    return merged


def _user_visible_config_texts(node_type: str, config: dict[str, Any]) -> list[str]:
    """Collect Builder-owned prose while excluding technical configuration values."""
    texts: list[str] = []
    for key in ("answer", "template", "agent_task", "prompt"):
        value = config.get(key)
        if isinstance(value, str):
            texts.append(value)
    for item in config.get("prompt_template") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            texts.append(item["text"])
    for item in config.get("variables") or []:
        if isinstance(item, dict) and isinstance(item.get("label"), str):
            texts.append(item["label"])
    if node_type == BuiltinNodeTypes.HUMAN_INPUT:
        for item in config.get("user_actions") or []:
            if isinstance(item, dict) and isinstance(item.get("title"), str):
                texts.append(item["title"])
    if node_type == BuiltinNodeTypes.QUESTION_CLASSIFIER:
        for item in config.get("classes") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                texts.append(item["name"])
    return texts


def _has_output_language_mismatch(node_type: str, config: dict[str, Any], language: OutputLanguage) -> bool:
    return any(
        not text_matches_output_language(text, language) for text in _user_visible_config_texts(node_type, config)
    )


def _build_node(
    *,
    client: LLMJsonClient,
    request: BuilderInput,
    target_node: dict[str, Any],
    plan_json: str,
    mode_section: str,
    existing_node: dict[str, Any] | None,
    emit: GenerationEventSink | None,
) -> dict[str, Any]:
    node_id = str(target_node.get("id") or "")
    node_type = str(target_node.get("node_type") or "")
    label = str(target_node.get("label") or node_id)
    if emit is not None:
        emit(
            (
                "operation",
                {
                    "stage": "building",
                    "action": "node_start",
                    "node_id": node_id,
                    "label": label,
                    "message": localized_generator_message("node_start", request.output_language, label=label),
                },
            )
        )

    model_section = ""
    if node_type in _MODEL_NODE_TYPES:
        model_section = (
            "# Selected model (copy verbatim)\n\n"
            f"provider={request.provider}, name={request.model_name}, mode={request.model_mode}\n\n"
        )
    existing_config_section = ""
    if existing_node:
        existing_data = existing_node.get("data") if isinstance(existing_node.get("data"), dict) else {}
        prompt_safe = _sanitize_existing_config_for_prompt(existing_data)
        existing_config_section = (
            "# Existing config to preserve unless the instruction changes it\n\n"
            f"{json.dumps(prompt_safe, ensure_ascii=False, separators=(',', ':'))}\n\n"
        )
    user_prompt = NODE_BUILDER_USER_PROMPT.format(
        node_id=node_id,
        node_type=node_type,
        label=str(target_node.get("label") or ""),
        purpose=str(target_node.get("purpose") or ""),
        output_language=output_language_name(request.output_language),
        instruction=request.instruction.strip(),
        ideal_output_section=format_ideal_output_section(request.ideal_output),
        mode_section=mode_section,
        model_section=model_section,
        tool_catalogue_section=(
            format_node_tool_catalogue_section(request.tool_catalogue_text)
            if node_type in {BuiltinNodeTypes.TOOL, BuiltinNodeTypes.AGENT}
            else ""
        ),
        knowledge_catalogue_section=(
            format_node_knowledge_catalogue_section(request.knowledge_catalogue_text)
            if node_type == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL
            else ""
        ),
        start_inputs_section=(
            format_start_inputs_section(request.start_inputs) if node_type == BuiltinNodeTypes.START else ""
        ),
        existing_config_section=existing_config_section,
        plan_json=plan_json,
    )
    messages = [
        SystemPromptMessage(content=get_node_builder_system_prompt(node_type)),
        UserPromptMessage(content=user_prompt),
    ]
    config: dict[str, Any] | None = None
    for attempt in range(2):
        response = client.iter_json(
            messages=messages if attempt == 0 else [*messages, UserPromptMessage(content=_LANGUAGE_RETRY_HINT)],
            stage=f"Builder {node_id}",
        )
        try:
            while True:
                delta = next(response)
                if emit is not None:
                    emit(("thought", {"stage": "builder", "delta": delta, "node_id": node_id}))
        except StopIteration as stop:
            parsed = cast(dict[str, Any], stop.value)
        candidate = parsed.get("config")
        if not isinstance(candidate, dict):
            raise StageSchemaError(f"Builder {node_id}", "missing 'config' object")
        config = candidate
        if not _has_output_language_mismatch(node_type, config, request.output_language):
            break
    if config is None:
        raise StageSchemaError(f"Builder {node_id}", "missing 'config' object")
    if _has_output_language_mismatch(node_type, config, request.output_language):
        raise StageSchemaError(
            f"Builder {node_id}",
            "user-visible config does not match requested "
            f"{output_language_name(request.output_language)} output language",
        )
    if emit is not None:
        emit(
            (
                "operation",
                {
                    "stage": "building",
                    "action": "node_done",
                    "node_id": node_id,
                    "label": label,
                    "message": localized_generator_message("node_done", request.output_language, label=label),
                },
            )
        )
    return config


def build_single_node(
    *,
    client: LLMJsonClient,
    request: BuilderInput,
    node_id: str,
    node_type: str,
    title: str,
    purpose: str,
    existing_node: dict[str, Any] | None = None,
    extra_plan_nodes: list[dict[str, Any]] | None = None,
    topology_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate one non-Tool node's config from intent. Does not write the graph.

    Workflow Assist compiles Tool intent in pure Python and this dedicated
    entry point rejects Tool nodes before any model call. The legacy full-graph
    builder remains separate for cmd+k. ``existing_node`` is prompt context; when its type matches
    ``node_type`` the generated fields are merged so an update is a delta.
    Replace (type change) uses the generated config as-is. Reserved wrapper
    keys are stripped so graph ops own ``type`` / ``title`` / ``desc`` / ``parentId``.

    ``topology_graph`` plus ``extra_plan_nodes`` become the Builder plan so an
    Assist create can see already-committed nodes and same-batch siblings.
    ``request.current_graph`` is the fallback topology (cmd+k / stale snapshot).
    """
    if node_type == BuiltinNodeTypes.TOOL:
        raise ValueError("Tool nodes are compiled outside Node Builder")
    target_node = {"id": node_id, "node_type": node_type, "label": title, "purpose": purpose}
    graph = topology_graph if isinstance(topology_graph, dict) else request.current_graph
    plan_nodes, plan_edges = _builder_topology_plan(
        graph,
        target_node=target_node,
        extra_plan_nodes=extra_plan_nodes or [],
    )
    start_inputs = request.start_inputs or _start_inputs_from_graph(graph)
    generated = _build_node(
        client=client,
        request=request,
        target_node=target_node,
        plan_json=format_parallel_plan(plan_nodes, plan_edges, start_inputs),
        mode_section=format_mode_section(request.mode),
        existing_node=existing_node,
        emit=None,
    )
    existing_data = existing_node.get("data") if existing_node and isinstance(existing_node.get("data"), dict) else None
    if isinstance(existing_data, dict) and existing_data.get("type") == node_type:
        config = _merge_generated_config(existing_data, generated)
    else:
        config = deepcopy(generated)
    for shared_key in ("type", "title", "desc", "selected", "parentId"):
        config.pop(shared_key, None)
    if node_type in CONTAINER_NODE_TYPES:
        config["start_node_id"] = resolve_container_start_node_id(node_id=node_id, data=config)
    return config


def build_graph(
    *,
    client: LLMJsonClient,
    request: BuilderInput,
    emit: GenerationEventSink | None = None,
) -> GraphDict:
    """Build changed node configs concurrently and expand the target graph."""
    existing_by_id = {
        str(node.get("id")): node
        for node in ((request.current_graph or {}).get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    existing_edges = [edge for edge in ((request.current_graph or {}).get("edges") or []) if isinstance(edge, dict)]
    nodes_to_build = [
        node
        for node in request.plan_nodes
        if not (node.get("action") == "keep" and str(node.get("id")) in existing_by_id)
    ]
    plan_json = format_parallel_plan(request.plan_nodes, request.plan_edges, request.start_inputs)
    mode_section = format_mode_section(request.mode)
    configs_by_id: dict[str, dict[str, Any]] = {}
    if nodes_to_build:
        max_workers = min(_node_builder_max_workers(), len(nodes_to_build))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="workflow-node-builder") as executor:
            futures = {
                executor.submit(
                    _build_node,
                    client=client,
                    request=request,
                    target_node=node,
                    plan_json=plan_json,
                    mode_section=mode_section,
                    existing_node=existing_by_id.get(str(node.get("id"))),
                    emit=emit,
                ): str(node.get("id"))
                for node in nodes_to_build
            }
            try:
                for future in as_completed(futures):
                    configs_by_id[futures[future]] = future.result()
            except BaseException:
                for pending in futures:
                    pending.cancel()
                raise
    return assemble_graph(
        plan_nodes=request.plan_nodes,
        plan_edges=request.plan_edges,
        configs_by_id=configs_by_id,
        existing_by_id=existing_by_id,
        existing_edges=existing_edges,
    )


def assemble_graph(
    *,
    plan_nodes: list[dict[str, Any]],
    plan_edges: list[dict[str, Any]],
    configs_by_id: dict[str, dict[str, Any]],
    existing_by_id: dict[str, dict[str, Any]],
    existing_edges: list[dict[str, Any]] | None = None,
) -> GraphDict:
    """Expand compact node configs and planner topology into graph JSON."""
    label_to_id = {
        str(node.get("label")): str(node.get("id")) for node in plan_nodes if node.get("label") and node.get("id")
    }
    type_by_id = {str(node.get("id")): str(node.get("node_type") or "") for node in plan_nodes}
    planned_node_ids = {str(node.get("id")) for node in plan_nodes if node.get("id")}
    children_by_parent: dict[str, list[str]] = {}
    start_by_parent: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for planned in plan_nodes:
        node_id = str(planned.get("id") or "")
        node_type = str(planned.get("node_type") or "")
        existing = existing_by_id.get(node_id)
        if planned.get("action") == "keep" and existing is not None:
            node = deepcopy(existing)
        else:
            generated_config = dict(configs_by_id.get(node_id) or {})
            existing_data = existing.get("data") if existing is not None else None
            config = (
                _merge_generated_config(existing_data, generated_config)
                if isinstance(existing_data, dict) and existing_data.get("type") == node_type
                else generated_config
            )
            for shared_key in ("type", "title", "desc", "selected"):
                config.pop(shared_key, None)
            data: dict[str, Any] = {
                "type": node_type,
                "title": str(planned.get("label") or node_id),
                "desc": str(planned.get("purpose") or ""),
                **config,
            }
            node = deepcopy(existing) if existing is not None else {"id": node_id}
            node["id"] = node_id
            node["data"] = data

        parent_ref = str(planned.get("parent") or "")
        parent_id = label_to_id.get(parent_ref, parent_ref)
        if not parent_id and planned.get("action") == "keep" and str(node.get("parentId") or "") in type_by_id:
            parent_id = str(node["parentId"])
        if parent_id:
            child_index = len(children_by_parent.get(parent_id, []))
            node["parentId"] = parent_id
            node.setdefault("position", {"x": 240 + 260 * child_index, "y": 60})
            node.setdefault("data", {})
            parent_type = type_by_id.get(parent_id)
            if parent_type == BuiltinNodeTypes.ITERATION:
                node["data"].setdefault("isInIteration", True)
                node["data"].setdefault("iteration_id", parent_id)
            elif parent_type == BuiltinNodeTypes.LOOP:
                node["data"].setdefault("isInLoop", True)
                node["data"].setdefault("loop_id", parent_id)
            children_by_parent.setdefault(parent_id, []).append(node_id)
        elif node.get("parentId"):
            for wrapper_key in ("parentId", "extent", "zIndex", "position", "positionAbsolute"):
                node.pop(wrapper_key, None)
            if isinstance(node.get("data"), dict):
                for marker_key in ("isInIteration", "iteration_id", "isInLoop", "loop_id"):
                    node["data"].pop(marker_key, None)
        nodes.append(node)
        if node_type in CONTAINER_NODE_TYPES:
            start_id = resolve_container_start_node_id(node_id=node_id, data=node.setdefault("data", {}))
            node.setdefault("data", {})["start_node_id"] = start_id
            start_by_parent[node_id] = start_id
            node.setdefault("width", 808)
            node.setdefault("height", 204)
            node.setdefault("zIndex", 1)
            is_iteration = node_type == BuiltinNodeTypes.ITERATION
            if start_id not in planned_node_ids:
                nodes.append(
                    {
                        "id": start_id,
                        "type": "custom-iteration-start" if is_iteration else "custom-loop-start",
                        "parentId": node_id,
                        "extent": "parent",
                        "draggable": False,
                        "selectable": False,
                        "zIndex": 1002,
                        "position": {"x": 60, "y": 78},
                        "data": {
                            "type": "iteration-start" if is_iteration else "loop-start",
                            "title": "",
                            "desc": "",
                            "selected": False,
                            "isInIteration" if is_iteration else "isInLoop": True,
                        },
                    }
                )

    edges: list[dict[str, Any]] = []
    for planned_edge in plan_edges:
        edge: dict[str, Any] = {
            "source": str(planned_edge.get("source") or ""),
            "target": str(planned_edge.get("target") or ""),
        }
        source_handle = planned_edge.get("source_handle") or planned_edge.get("sourceHandle")
        target_handle = planned_edge.get("target_handle") or planned_edge.get("targetHandle")
        if source_handle:
            edge["sourceHandle"] = str(source_handle)
        if target_handle:
            edge["targetHandle"] = str(target_handle)
        edges.append(edge)
    planned_sources = {str(edge.get("source") or "") for edge in edges}
    existing_entry_targets = {
        str(edge.get("source") or ""): str(edge.get("target") or "") for edge in (existing_edges or [])
    }
    for parent_id, child_ids in children_by_parent.items():
        start_id = start_by_parent.get(parent_id, resolve_container_start_node_id(node_id=parent_id, data={}))
        if not child_ids or start_id in planned_sources:
            continue
        preferred = existing_entry_targets.get(start_id, "")
        entry_target = preferred if preferred in child_ids else child_ids[0]
        edges.append({"source": start_id, "target": entry_target})
    for child_ids in children_by_parent.values():
        internal_sources = {
            str(edge.get("source") or "")
            for edge in edges
            if str(edge.get("source") or "") in child_ids and str(edge.get("target") or "") in child_ids
        }
        for source_id, target_id in zip(child_ids, child_ids[1:]):
            if source_id not in internal_sources:
                edges.append({"source": source_id, "target": target_id})
    return cast(GraphDict, {"nodes": nodes, "edges": edges, "viewport": _DEFAULT_VIEWPORT})
